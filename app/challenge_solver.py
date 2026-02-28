"""
Cloudflare Challenge Solver for gnosis-crawl.

Detects and waits for Cloudflare challenges to auto-resolve on Playwright pages.
Falls back to CapSolver API for visible Turnstile challenges that don't auto-resolve.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ChallengeType(str, Enum):
    """Types of Cloudflare challenges."""
    TURNSTILE = "turnstile"
    JS_CHALLENGE = "js_challenge"
    BROWSER_CHECK = "browser_check"
    MANAGED = "managed_challenge"
    NONE = "none"


@dataclass
class ChallengeDetection:
    """Result of challenge detection."""
    detected: bool = False
    challenge_type: ChallengeType = ChallengeType.NONE
    confidence: float = 0.0
    selector_matched: str = ""


@dataclass
class ChallengeResult:
    """Result of challenge resolution attempt."""
    resolved: bool = False
    challenge_type: ChallengeType = ChallengeType.NONE
    method: str = "none"  # "auto_resolve", "capsolver", "none"
    wait_time_ms: int = 0
    error: Optional[str] = None


# Selectors that indicate a Cloudflare challenge is present
CHALLENGE_SELECTORS = [
    ('#challenge-running', ChallengeType.JS_CHALLENGE),
    ('#challenge-stage', ChallengeType.JS_CHALLENGE),
    ('.cf-browser-verification', ChallengeType.BROWSER_CHECK),
    ('iframe[src*="challenges.cloudflare.com"]', ChallengeType.TURNSTILE),
    ('#turnstile-wrapper', ChallengeType.TURNSTILE),
    ('#cf-challenge-running', ChallengeType.MANAGED),
    ('.cf-turnstile', ChallengeType.TURNSTILE),
]

# Selectors that indicate the challenge has been resolved
RESOLVED_SELECTORS = [
    '#challenge-success',
    '#challenge-stage[style*="display: none"]',
]

# Title patterns that indicate a challenge page
CHALLENGE_TITLE_PATTERNS = [
    # English
    'just a moment',
    'attention required',
    'checking your browser',
    'please wait',
    'one more step',
    'verify you are human',
    # Portuguese
    'um momento',
    'verificação de segurança',
    # Spanish
    'un momento',
    'verificación de seguridad',
    # French
    'un instant',
    'vérification de sécurité',
    # German
    'einen moment',
    'sicherheitsüberprüfung',
]


async def detect_challenge(page) -> ChallengeDetection:
    """
    Detect if a Cloudflare challenge is present on the page.

    Args:
        page: Playwright page object

    Returns:
        ChallengeDetection with type and confidence
    """
    # Check title first (fast)
    try:
        title = await page.title()
        title_lower = title.lower() if title else ""
        for pattern in CHALLENGE_TITLE_PATTERNS:
            if pattern in title_lower:
                return ChallengeDetection(
                    detected=True,
                    challenge_type=ChallengeType.JS_CHALLENGE,
                    confidence=0.9,
                    selector_matched=f"title:{pattern}",
                )
    except Exception:
        pass

    # Check DOM selectors
    for selector, challenge_type in CHALLENGE_SELECTORS:
        try:
            element = await page.query_selector(selector)
            if element:
                visible = await element.is_visible()
                confidence = 0.95 if visible else 0.7
                return ChallengeDetection(
                    detected=True,
                    challenge_type=challenge_type,
                    confidence=confidence,
                    selector_matched=selector,
                )
        except Exception:
            continue

    # Content-based heuristic: if page has very little content and mentions
    # Cloudflare/challenge keywords, it's likely a challenge page even without
    # standard selectors (some Cloudflare configs use custom interstitials)
    try:
        content = await page.content()
        if content and len(content) < 10000:
            content_lower = content.lower()
            cf_signals = [
                "cloudflare", "cf-browser-verification", "ray id",
                "challenge-platform", "turnstile", "cf_chl_opt",
                "performance & security by",
            ]
            matched_signals = [s for s in cf_signals if s in content_lower]
            if len(matched_signals) >= 2:
                logger.info(f"Challenge detected via content heuristic: {matched_signals}")
                return ChallengeDetection(
                    detected=True,
                    challenge_type=ChallengeType.MANAGED,
                    confidence=0.8,
                    selector_matched=f"content_heuristic:{','.join(matched_signals[:3])}",
                )
    except Exception:
        pass

    return ChallengeDetection(detected=False)


async def wait_for_challenge_resolution(
    page,
    timeout_ms: int = 15000,
    poll_interval_ms: int = 500,
) -> ChallengeResult:
    """
    Wait for a Cloudflare challenge to auto-resolve.

    Many Turnstile challenges are invisible and auto-resolve within seconds.
    This function polls the page to detect when the challenge is gone.
    """
    detection = await detect_challenge(page)
    if not detection.detected:
        return ChallengeResult(resolved=True, method="none", wait_time_ms=0)

    start_ms = int(asyncio.get_event_loop().time() * 1000)
    elapsed = 0

    while elapsed < timeout_ms:
        await asyncio.sleep(poll_interval_ms / 1000)
        elapsed = int(asyncio.get_event_loop().time() * 1000) - start_ms

        # Check if challenge resolved
        current = await detect_challenge(page)
        if not current.detected:
            return ChallengeResult(
                resolved=True,
                challenge_type=detection.challenge_type,
                method="auto_resolve",
                wait_time_ms=elapsed,
            )

        # Check for resolved indicators
        for sel in RESOLVED_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el:
                    return ChallengeResult(
                        resolved=True,
                        challenge_type=detection.challenge_type,
                        method="auto_resolve",
                        wait_time_ms=elapsed,
                    )
            except Exception:
                continue

    # Timeout — challenge didn't auto-resolve
    return ChallengeResult(
        resolved=False,
        challenge_type=detection.challenge_type,
        method="none",
        wait_time_ms=elapsed,
        error=f"Challenge auto-resolve timeout after {timeout_ms}ms",
    )


async def solve_turnstile_capsolver(
    page,
    site_url: str,
    api_key: Optional[str] = None,
    timeout_ms: int = 30000,
) -> ChallengeResult:
    """
    Attempt to solve a visible Turnstile challenge via CapSolver API.

    Only called when auto-resolve fails and a visible Turnstile is detected.
    Requires CAPSOLVER_API_KEY environment variable.
    """
    key = api_key or os.environ.get("CAPSOLVER_API_KEY")
    if not key:
        logger.warning("CAPSOLVER_API_KEY not configured — CapSolver fallback disabled")
        return ChallengeResult(
            resolved=False,
            challenge_type=ChallengeType.TURNSTILE,
            method="none",
            error="CAPSOLVER_API_KEY not configured",
        )

    start_ms = int(asyncio.get_event_loop().time() * 1000)

    try:
        # Extract sitekey from Turnstile iframe/widget
        sitekey = await _extract_turnstile_sitekey(page)
        if not sitekey:
            return ChallengeResult(
                resolved=False,
                challenge_type=ChallengeType.TURNSTILE,
                method="none",
                error="Could not extract Turnstile sitekey",
            )

        # Call CapSolver API
        token = await _call_capsolver(key, site_url, sitekey, timeout_ms)
        if not token:
            elapsed = int(asyncio.get_event_loop().time() * 1000) - start_ms
            return ChallengeResult(
                resolved=False,
                challenge_type=ChallengeType.TURNSTILE,
                method="capsolver",
                wait_time_ms=elapsed,
                error="CapSolver failed to return token",
            )

        # Inject token into the page
        await _inject_turnstile_token(page, token)

        # Wait briefly for page to process the token
        await asyncio.sleep(2)

        # Verify resolution
        current = await detect_challenge(page)
        elapsed = int(asyncio.get_event_loop().time() * 1000) - start_ms

        if not current.detected:
            return ChallengeResult(
                resolved=True,
                challenge_type=ChallengeType.TURNSTILE,
                method="capsolver",
                wait_time_ms=elapsed,
            )
        else:
            return ChallengeResult(
                resolved=False,
                challenge_type=ChallengeType.TURNSTILE,
                method="capsolver",
                wait_time_ms=elapsed,
                error="Token injected but challenge still present",
            )

    except Exception as e:
        elapsed = int(asyncio.get_event_loop().time() * 1000) - start_ms
        return ChallengeResult(
            resolved=False,
            challenge_type=ChallengeType.TURNSTILE,
            method="capsolver",
            wait_time_ms=elapsed,
            error=str(e),
        )


async def resolve_challenge(
    page,
    site_url: str,
    auto_wait_ms: int = 15000,
    capsolver_timeout_ms: int = 30000,
) -> ChallengeResult:
    """
    Full challenge resolution pipeline:
    1. Detect if challenge is present
    2. Wait for auto-resolve (invisible Turnstile, JS challenges)
    3. If still blocked and Turnstile visible, try CapSolver
    """
    detection = await detect_challenge(page)
    if not detection.detected:
        return ChallengeResult(resolved=True, method="none", wait_time_ms=0)

    logger.info(f"Challenge detected: {detection.challenge_type} (confidence: {detection.confidence}, selector: {detection.selector_matched})")

    # Step 1: Try auto-resolve
    auto_result = await wait_for_challenge_resolution(page, timeout_ms=auto_wait_ms)
    if auto_result.resolved:
        logger.info(f"Challenge auto-resolved in {auto_result.wait_time_ms}ms")
        return auto_result

    # Step 2: If Turnstile or managed challenge, try CapSolver
    # Managed challenges often embed Turnstile under the hood
    if detection.challenge_type in (ChallengeType.TURNSTILE, ChallengeType.MANAGED):
        logger.info("Attempting CapSolver for Turnstile challenge")
        capsolver_result = await solve_turnstile_capsolver(
            page, site_url, timeout_ms=capsolver_timeout_ms
        )
        if capsolver_result.resolved:
            total_ms = auto_result.wait_time_ms + capsolver_result.wait_time_ms
            return ChallengeResult(
                resolved=True,
                challenge_type=ChallengeType.TURNSTILE,
                method="capsolver",
                wait_time_ms=total_ms,
            )

    # All attempts failed
    total_ms = auto_result.wait_time_ms
    return ChallengeResult(
        resolved=False,
        challenge_type=detection.challenge_type,
        method="none",
        wait_time_ms=total_ms,
        error=auto_result.error or "Challenge not resolved",
    )


# --- Internal helpers ---

async def _extract_turnstile_sitekey(page) -> Optional[str]:
    """Extract the Turnstile sitekey from the page."""
    selectors = [
        '.cf-turnstile[data-sitekey]',
        'div[data-turnstile-sitekey]',
        'iframe[src*="challenges.cloudflare.com"]',
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                sitekey = await el.get_attribute('data-sitekey') or await el.get_attribute('data-turnstile-sitekey')
                if sitekey:
                    return sitekey
                # Try extracting from iframe src
                src = await el.get_attribute('src')
                if src and 'sitekey=' in src:
                    return src.split('sitekey=')[1].split('&')[0]
        except Exception:
            continue
    return None


async def _call_capsolver(
    api_key: str,
    site_url: str,
    sitekey: str,
    timeout_ms: int,
) -> Optional[str]:
    """Call CapSolver API to solve Turnstile. Returns token or None."""
    import aiohttp

    create_url = "https://api.capsolver.com/createTask"
    result_url = "https://api.capsolver.com/getTaskResult"

    payload = {
        "clientKey": api_key,
        "task": {
            "type": "AntiTurnstileTaskProxyLess",
            "websiteURL": site_url,
            "websiteKey": sitekey,
        },
    }

    try:
        async with aiohttp.ClientSession() as session:
            # Create task
            async with session.post(create_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if data.get("errorId", 1) != 0:
                    logger.warning(f"CapSolver create error: {data.get('errorDescription')}")
                    return None
                task_id = data.get("taskId")
                if not task_id:
                    return None

            # Poll for result
            poll_payload = {"clientKey": api_key, "taskId": task_id}
            elapsed = 0
            while elapsed < timeout_ms:
                await asyncio.sleep(3)
                elapsed += 3000
                async with session.post(result_url, json=poll_payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                    status = data.get("status")
                    if status == "ready":
                        return data.get("solution", {}).get("token")
                    if status == "failed":
                        logger.warning(f"CapSolver task failed: {data.get('errorDescription')}")
                        return None

            logger.warning(f"CapSolver timeout after {timeout_ms}ms")
            return None

    except Exception as e:
        logger.warning(f"CapSolver error: {e}")
        return None


async def _inject_turnstile_token(page, token: str):
    """Inject the solved Turnstile token and trigger Cloudflare's callback."""
    await page.evaluate(f"""() => {{
        // Set token in known Turnstile response inputs
        const inputs = document.querySelectorAll('input[name="cf-turnstile-response"]');
        inputs.forEach(input => {{ input.value = '{token}'; }});

        const hiddenInputs = document.querySelectorAll('[name*="turnstile"]');
        hiddenInputs.forEach(input => {{ input.value = '{token}'; }});

        // Trigger Cloudflare's callback to process the token
        // Method 1: Call turnstile callback if available on the widget
        const widgets = document.querySelectorAll('.cf-turnstile, [data-turnstile-sitekey]');
        for (const w of widgets) {{
            const callbackName = w.getAttribute('data-callback');
            if (callbackName && typeof window[callbackName] === 'function') {{
                window[callbackName]('{token}');
            }}
        }}

        // Method 2: Submit the challenge form if present
        const forms = document.querySelectorAll('form[action*="challenge"]');
        if (forms.length > 0) {{
            forms[0].submit();
        }}

        // Method 3: Dispatch input event to trigger any listeners
        inputs.forEach(input => {{
            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }});
    }}""")
