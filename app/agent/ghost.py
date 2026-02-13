"""Ghost Protocol: vision-based fallback for anti-bot blocked pages.

When a crawl result signals an anti-bot block (Cloudflare challenge, CAPTCHA,
empty SPA shell), the Ghost Protocol:

1. Takes a full-page screenshot via Playwright
2. Sends the image to a vision-capable LLM (Claude or GPT-4o)
3. Extracts content from the rendered pixels
4. Returns extracted text with render_mode="ghost" in the result

This bypasses DOM-based anti-bot detection entirely because the content
is read from the visual rendering, not the DOM.

Requires AGENT_GHOST_ENABLED=true.
Auto-triggers on detected blocks when AGENT_GHOST_AUTO_TRIGGER=true.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Block detection
# ---------------------------------------------------------------------------

class BlockSignal(str, Enum):
    """Categorized anti-bot block signals."""
    CLOUDFLARE = "cloudflare_challenge"
    CAPTCHA = "captcha"
    SESSION_VERIFY = "session_verification"
    ACCESS_DENIED = "access_denied"
    BOT_CHALLENGE = "bot_challenge"
    EMPTY_SHELL = "empty_spa_shell"
    HTTP_403 = "http_403"
    HTTP_429 = "http_429"
    HTTP_503 = "http_503"


@dataclass
class BlockDetection:
    """Result of block signal analysis."""
    blocked: bool = False
    signal: Optional[BlockSignal] = None
    reason: str = ""
    captcha_detected: bool = False
    confidence: float = 0.0


# Phrases that indicate anti-bot blocking, ordered by specificity
_BLOCK_PATTERNS: List[tuple[str, BlockSignal, float]] = [
    ("cloudflare", BlockSignal.CLOUDFLARE, 0.95),
    ("verify your session", BlockSignal.SESSION_VERIFY, 0.9),
    ("captcha", BlockSignal.CAPTCHA, 0.95),
    ("recaptcha", BlockSignal.CAPTCHA, 0.95),
    ("hcaptcha", BlockSignal.CAPTCHA, 0.95),
    ("access denied", BlockSignal.ACCESS_DENIED, 0.8),
    ("just a moment", BlockSignal.BOT_CHALLENGE, 0.85),
    ("are you human", BlockSignal.BOT_CHALLENGE, 0.9),
    ("attention required", BlockSignal.BOT_CHALLENGE, 0.85),
    ("checking your browser", BlockSignal.BOT_CHALLENGE, 0.9),
    ("please wait while we verify", BlockSignal.BOT_CHALLENGE, 0.9),
    ("enable javascript and cookies", BlockSignal.BOT_CHALLENGE, 0.8),
]

# Minimum content thresholds that suggest an empty SPA shell
_EMPTY_SHELL_CHAR_THRESHOLD = 200
_EMPTY_SHELL_WORD_THRESHOLD = 30


def detect_block(
    *,
    html: str = "",
    markdown: str = "",
    status_code: Optional[int] = None,
    body_char_count: int = 0,
    body_word_count: int = 0,
    content_quality: str = "",
) -> BlockDetection:
    """Analyze crawl output for anti-bot block signals.

    Returns a BlockDetection with blocked=True if the page appears to be
    an anti-bot challenge, CAPTCHA, or empty SPA shell.
    """
    combined = f"{html or ''}\n{markdown or ''}".lower()

    # Pattern matching
    for phrase, signal, confidence in _BLOCK_PATTERNS:
        if phrase in combined:
            return BlockDetection(
                blocked=True,
                signal=signal,
                reason=f"Detected '{phrase}' in page content",
                captcha_detected=signal == BlockSignal.CAPTCHA,
                confidence=confidence,
            )

    # HTTP status codes that indicate blocking
    if status_code == 403:
        return BlockDetection(
            blocked=True,
            signal=BlockSignal.HTTP_403,
            reason="HTTP 403 Forbidden",
            confidence=0.7,
        )
    if status_code == 429:
        return BlockDetection(
            blocked=True,
            signal=BlockSignal.HTTP_429,
            reason="HTTP 429 Too Many Requests",
            confidence=0.8,
        )
    if status_code == 503:
        return BlockDetection(
            blocked=True,
            signal=BlockSignal.HTTP_503,
            reason="HTTP 503 Service Unavailable (common anti-bot response)",
            confidence=0.75,
        )

    # Empty SPA shell detection
    if (
        body_char_count < _EMPTY_SHELL_CHAR_THRESHOLD
        and body_word_count < _EMPTY_SHELL_WORD_THRESHOLD
        and html  # has HTML but very little text content
        and len(html) > 500  # the HTML itself is non-trivial (JS-heavy shell)
    ):
        return BlockDetection(
            blocked=True,
            signal=BlockSignal.EMPTY_SHELL,
            reason="Empty SPA shell: HTML present but minimal text content",
            confidence=0.6,
        )

    # Content quality flag from crawler
    if content_quality == "blocked":
        return BlockDetection(
            blocked=True,
            signal=BlockSignal.BOT_CHALLENGE,
            reason="Crawler classified content_quality as 'blocked'",
            confidence=0.85,
        )

    return BlockDetection(blocked=False)


def should_trigger_ghost(
    detection: BlockDetection,
    *,
    ghost_enabled: bool = False,
    auto_trigger: bool = True,
) -> bool:
    """Determine whether to activate Ghost Protocol for this detection."""
    if not ghost_enabled:
        return False
    if not detection.blocked:
        return False
    if not auto_trigger:
        return False
    # Don't ghost on simple access denied (likely auth issue, not anti-bot)
    if detection.signal == BlockSignal.ACCESS_DENIED and detection.confidence < 0.85:
        return False
    return True


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------

@dataclass
class GhostCapture:
    """Result of a Ghost Protocol screenshot capture."""
    success: bool = False
    image_bytes: bytes = b""
    content_type: str = "image/png"
    width: int = 0
    height: int = 0
    url: str = ""
    capture_ms: int = 0
    error: Optional[str] = None


async def capture_screenshot(
    url: str,
    *,
    max_width: int = 1280,
    timeout: int = 30,
    javascript: bool = True,
) -> GhostCapture:
    """Take a full-page screenshot of a URL using Playwright.

    This creates a fresh browser context to avoid any cached challenge state,
    and captures the page as it appears visually (including any anti-bot
    challenge pages, CAPTCHAs, etc.).

    Args:
        url: The URL to screenshot.
        max_width: Maximum viewport width.
        timeout: Navigation timeout in seconds.
        javascript: Whether to enable JavaScript.

    Returns:
        GhostCapture with image bytes on success.
    """
    start = time.monotonic()

    try:
        from app.browser import get_browser_engine
        browser = await get_browser_engine()

        # Use the existing crawl_with_context which handles retries and cleanup
        html, page_info, screenshot_data = await browser.crawl_with_context(
            url=url,
            javascript_enabled=javascript,
            timeout=timeout * 1000,
            take_screenshot=True,
            wait_until="networkidle",  # wait for full render
            wait_after_load_ms=2000,  # extra wait for challenge pages
        )

        capture_ms = int((time.monotonic() - start) * 1000)

        if screenshot_data is None:
            return GhostCapture(
                success=False,
                url=url,
                capture_ms=capture_ms,
                error="Screenshot capture returned None",
            )

        # Handle segmented screenshots — for ghost we want the first segment
        # (the visible viewport) which usually contains the content
        if isinstance(screenshot_data, list):
            image_bytes = screenshot_data[0]
        else:
            image_bytes = screenshot_data

        return GhostCapture(
            success=True,
            image_bytes=image_bytes,
            url=url,
            capture_ms=capture_ms,
        )

    except Exception as exc:
        capture_ms = int((time.monotonic() - start) * 1000)
        logger.error("Ghost screenshot capture failed for %s: %s", url, exc, exc_info=True)
        return GhostCapture(
            success=False,
            url=url,
            capture_ms=capture_ms,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Vision extraction
# ---------------------------------------------------------------------------

GHOST_EXTRACTION_PROMPT = """You are extracting readable text content from a screenshot of a web page.

The page may show an anti-bot challenge, CAPTCHA, or the actual content behind it.

Instructions:
1. If you can see actual page content (articles, text, data), extract ALL of it faithfully.
2. If you see an anti-bot challenge or CAPTCHA page, describe what you see and note that the content is blocked.
3. Preserve the structure: use headings, lists, and paragraphs as they appear visually.
4. Do NOT add commentary or analysis — just extract what you see on the page.
5. If there are tables, reproduce them in markdown table format.
6. If there are images with alt text or captions, note them in brackets like [Image: description].

Extract the content now:"""


@dataclass
class GhostExtraction:
    """Result of vision-based content extraction."""
    success: bool = False
    content: str = ""
    render_mode: str = "ghost"
    extraction_ms: int = 0
    provider: str = ""
    blocked_content: bool = False  # True if vision shows the page IS a challenge
    error: Optional[str] = None


async def extract_via_vision(
    capture: GhostCapture,
    *,
    provider: Optional[Any] = None,
    prompt: str = GHOST_EXTRACTION_PROMPT,
) -> GhostExtraction:
    """Send a screenshot to a vision-capable LLM and extract text content.

    Args:
        capture: The GhostCapture containing screenshot bytes.
        provider: An LLMAdapter instance with vision() support.
        prompt: The extraction prompt.

    Returns:
        GhostExtraction with extracted content.
    """
    if not capture.success or not capture.image_bytes:
        return GhostExtraction(
            success=False,
            error=capture.error or "No screenshot data available",
        )

    if provider is None:
        return GhostExtraction(
            success=False,
            error="No vision provider configured",
        )

    start = time.monotonic()

    try:
        extracted_text = await provider.vision(
            capture.image_bytes,
            prompt,
            detail="high",  # high detail for text extraction
        )

        extraction_ms = int((time.monotonic() - start) * 1000)

        # Check if the extracted content indicates the page itself is blocked
        blocked_indicators = [
            "anti-bot", "captcha", "challenge", "verify you are human",
            "access denied", "please complete the security check",
        ]
        content_lower = extracted_text.lower()
        blocked_content = any(ind in content_lower for ind in blocked_indicators)

        return GhostExtraction(
            success=True,
            content=extracted_text,
            render_mode="ghost",
            extraction_ms=extraction_ms,
            provider=provider.__class__.__name__,
            blocked_content=blocked_content,
        )

    except NotImplementedError:
        extraction_ms = int((time.monotonic() - start) * 1000)
        return GhostExtraction(
            success=False,
            extraction_ms=extraction_ms,
            error=f"Provider {provider.__class__.__name__} does not support vision",
        )
    except Exception as exc:
        extraction_ms = int((time.monotonic() - start) * 1000)
        logger.error("Ghost vision extraction failed: %s", exc, exc_info=True)
        return GhostExtraction(
            success=False,
            extraction_ms=extraction_ms,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Full Ghost Protocol pipeline
# ---------------------------------------------------------------------------

@dataclass
class GhostResult:
    """Complete result from the Ghost Protocol pipeline."""
    success: bool = False
    url: str = ""
    content: str = ""
    render_mode: str = "ghost"
    block_signal: Optional[str] = None
    block_reason: str = ""
    capture_ms: int = 0
    extraction_ms: int = 0
    total_ms: int = 0
    provider: str = ""
    blocked_content: bool = False
    error: Optional[str] = None


async def run_ghost_protocol(
    url: str,
    *,
    provider: Optional[Any] = None,
    max_width: int = 1280,
    timeout: int = 30,
    prompt: str = GHOST_EXTRACTION_PROMPT,
    block_detection: Optional[BlockDetection] = None,
) -> GhostResult:
    """Execute the full Ghost Protocol pipeline.

    1. Capture screenshot
    2. Send to vision LLM
    3. Return extracted content

    Args:
        url: URL to ghost-extract.
        provider: Vision-capable LLMAdapter.
        max_width: Max viewport width.
        timeout: Navigation timeout.
        prompt: Vision extraction prompt.
        block_detection: Optional pre-computed block detection result.

    Returns:
        GhostResult with extracted content or error.
    """
    pipeline_start = time.monotonic()

    logger.info("Ghost Protocol activated for %s", url)

    # Step 1: Capture screenshot
    capture = await capture_screenshot(
        url,
        max_width=max_width,
        timeout=timeout,
    )

    if not capture.success:
        total_ms = int((time.monotonic() - pipeline_start) * 1000)
        return GhostResult(
            success=False,
            url=url,
            capture_ms=capture.capture_ms,
            total_ms=total_ms,
            block_signal=block_detection.signal.value if block_detection and block_detection.signal else None,
            block_reason=block_detection.reason if block_detection else "",
            error=f"Screenshot capture failed: {capture.error}",
        )

    # Step 2: Vision extraction
    extraction = await extract_via_vision(
        capture,
        provider=provider,
        prompt=prompt,
    )

    total_ms = int((time.monotonic() - pipeline_start) * 1000)

    if not extraction.success:
        return GhostResult(
            success=False,
            url=url,
            capture_ms=capture.capture_ms,
            extraction_ms=extraction.extraction_ms,
            total_ms=total_ms,
            block_signal=block_detection.signal.value if block_detection and block_detection.signal else None,
            block_reason=block_detection.reason if block_detection else "",
            error=f"Vision extraction failed: {extraction.error}",
        )

    logger.info(
        "Ghost Protocol complete for %s: %d chars extracted in %dms (capture=%dms, extract=%dms)",
        url,
        len(extraction.content),
        total_ms,
        capture.capture_ms,
        extraction.extraction_ms,
    )

    return GhostResult(
        success=True,
        url=url,
        content=extraction.content,
        render_mode="ghost",
        block_signal=block_detection.signal.value if block_detection and block_detection.signal else None,
        block_reason=block_detection.reason if block_detection else "",
        capture_ms=capture.capture_ms,
        extraction_ms=extraction.extraction_ms,
        total_ms=total_ms,
        provider=extraction.provider,
        blocked_content=extraction.blocked_content,
    )


# ---------------------------------------------------------------------------
# Vision provider factory (for ghost-specific provider override)
# ---------------------------------------------------------------------------

def create_ghost_provider():
    """Create a vision-capable provider for Ghost Protocol.

    Uses AGENT_GHOST_VISION_PROVIDER if set, otherwise falls back
    to the main AGENT_PROVIDER.
    """
    from app.config import settings
    from app.agent.providers.base import create_provider, _pick_key, _pick_model, _pick_base_url

    provider_name = settings.agent_ghost_vision_provider or settings.agent_provider

    return create_provider(
        provider_name,
        api_key=_pick_key(settings, provider_name),
        model=_pick_model(settings, provider_name),
        base_url=_pick_base_url(settings, provider_name),
    )
