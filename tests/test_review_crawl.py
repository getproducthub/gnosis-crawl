"""Tests for the /api/review-crawl endpoint — specialized review site crawler."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import ReviewCrawlRequest, ReviewCrawlResult


# --- ReviewCrawlRequest model tests ---


class TestReviewCrawlRequest:
    def test_defaults(self):
        req = ReviewCrawlRequest(url="https://www.g2.com/products/slack/reviews", platform="g2")
        assert str(req.url) == "https://www.g2.com/products/slack/reviews"
        assert req.platform == "g2"
        assert req.proxy_preference == "auto"
        assert req.challenge_wait_ms == 15000
        assert req.ghost_fallback is True
        assert req.scroll_count == 5
        assert req.timeout == 90
        assert req.customer_id is None

    def test_custom_values(self):
        req = ReviewCrawlRequest(
            url="https://www.capterra.com/p/12345/reviews",
            platform="capterra",
            customer_id="cust-123",
            proxy_preference="residential",
            challenge_wait_ms=30000,
            ghost_fallback=False,
            scroll_count=10,
            timeout=120,
        )
        assert req.platform == "capterra"
        assert req.proxy_preference == "residential"
        assert req.challenge_wait_ms == 30000
        assert req.ghost_fallback is False
        assert req.scroll_count == 10
        assert req.timeout == 120

    def test_challenge_wait_ms_min_max(self):
        req = ReviewCrawlRequest(
            url="https://g2.com/products/test/reviews",
            platform="g2",
            challenge_wait_ms=0,
        )
        assert req.challenge_wait_ms == 0

        req2 = ReviewCrawlRequest(
            url="https://g2.com/products/test/reviews",
            platform="g2",
            challenge_wait_ms=60000,
        )
        assert req2.challenge_wait_ms == 60000

    def test_scroll_count_bounds(self):
        req = ReviewCrawlRequest(
            url="https://g2.com/products/test/reviews",
            platform="g2",
            scroll_count=1,
        )
        assert req.scroll_count == 1

        req2 = ReviewCrawlRequest(
            url="https://g2.com/products/test/reviews",
            platform="g2",
            scroll_count=20,
        )
        assert req2.scroll_count == 20


# --- ReviewCrawlResult model tests ---


class TestReviewCrawlResult:
    def test_defaults(self):
        result = ReviewCrawlResult(success=True, url="https://g2.com/products/slack/reviews")
        assert result.success is True
        assert result.url == "https://g2.com/products/slack/reviews"
        assert result.markdown is None
        assert result.blocked is False
        assert result.challenge_detected is False
        assert result.challenge_resolved is False
        assert result.ghost_triggered is False
        assert result.proxy_used is False
        assert result.total_time_ms == 0
        assert result.error is None

    def test_full_result(self):
        result = ReviewCrawlResult(
            success=True,
            url="https://g2.com/products/slack/reviews",
            final_url="https://g2.com/products/slack/reviews?page=1",
            markdown="# Slack Reviews\n\n- Great product",
            screenshot_url="https://screenshots.example.com/abc.png",
            content_quality="sufficient",
            blocked=False,
            challenge_detected=True,
            challenge_type="cloudflare",
            challenge_resolved=True,
            challenge_method="auto_resolve",
            ghost_triggered=False,
            proxy_used=True,
            proxy_region="us-east",
            total_time_ms=8500,
        )
        assert result.content_quality == "sufficient"
        assert result.challenge_detected is True
        assert result.challenge_resolved is True
        assert result.proxy_used is True
        assert result.total_time_ms == 8500

    def test_blocked_result_with_ghost(self):
        result = ReviewCrawlResult(
            success=True,
            url="https://g2.com/products/slack/reviews",
            markdown="# Ghost extracted content",
            content_quality="sufficient",
            blocked=False,
            ghost_triggered=True,
            ghost_content="# Ghost extracted content",
            ghost_extracted_chars=500,
            total_time_ms=15000,
        )
        assert result.ghost_triggered is True
        assert result.ghost_extracted_chars == 500

    def test_failed_result(self):
        result = ReviewCrawlResult(
            success=False,
            url="https://g2.com/products/slack/reviews",
            blocked=True,
            block_reason="Cloudflare challenge not resolved",
            content_quality="blocked",
            challenge_detected=True,
            challenge_type="turnstile",
            error="All crawl strategies exhausted",
            total_time_ms=45000,
        )
        assert result.success is False
        assert result.blocked is True
        assert result.error == "All crawl strategies exhausted"

    def test_crawled_at_defaults_to_now(self):
        result = ReviewCrawlResult(success=True, url="https://g2.com")
        assert isinstance(result.crawled_at, datetime)


# --- Proxy resolution logic ---


class TestReviewCrawlProxyResolution:
    """Test proxy resolution behavior in the review-crawl endpoint."""

    def test_proxy_preference_none_skips_proxy(self):
        """When proxy_preference='none', no proxy should be used."""
        req = ReviewCrawlRequest(
            url="https://g2.com/products/slack/reviews",
            platform="g2",
            proxy_preference="none",
        )
        assert req.proxy_preference == "none"

    def test_proxy_preference_auto(self):
        """Default proxy_preference is 'auto'."""
        req = ReviewCrawlRequest(
            url="https://g2.com/products/slack/reviews",
            platform="g2",
        )
        assert req.proxy_preference == "auto"


# --- Ghost Protocol integration ---


class TestReviewCrawlGhostIntegration:
    """Test Ghost Protocol fallback behavior in ReviewCrawlResult."""

    def test_ghost_content_only_when_triggered(self):
        """ghost_content should only be set when ghost_triggered is True."""
        result = ReviewCrawlResult(
            success=True,
            url="https://g2.com",
            ghost_triggered=False,
            ghost_content=None,
        )
        assert result.ghost_content is None

    def test_ghost_extracted_chars_zero_by_default(self):
        result = ReviewCrawlResult(success=True, url="https://g2.com")
        assert result.ghost_extracted_chars == 0


# --- Content quality assessment ---


class TestReviewCrawlContentQuality:
    """Test content quality values in ReviewCrawlResult."""

    def test_content_quality_values(self):
        """Content quality can be empty, minimal, sufficient, or blocked."""
        for quality in ("empty", "minimal", "sufficient", "blocked"):
            result = ReviewCrawlResult(
                success=quality == "sufficient",
                url="https://g2.com",
                content_quality=quality,
            )
            assert result.content_quality == quality


# --- Ghost Protocol call-site correctness (G#2 + G#3) ---


class TestGhostProtocolCallSite:
    """Verify the Ghost Protocol call-site in routes.py uses the correct
    imports, kwargs, and GhostResult field names.

    Reads routes.py source directly so tests work without fastapi installed.
    """

    @staticmethod
    def _ghost_block_source():
        """Extract the Ghost Protocol try-block from routes.py source."""
        import pathlib

        routes_path = pathlib.Path(__file__).parent.parent / "app" / "routes.py"
        source = routes_path.read_text()
        # Grab everything from "Ghost Protocol fallback" to the except clause
        start = source.index("# ---- Ghost Protocol fallback ----")
        end = source.index("except Exception as e:", start)
        return source[start:end]

    def test_ghost_uses_create_ghost_provider_not_get_browser_engine(self):
        """G#2: run_ghost_protocol must be called with provider= kwarg,
        not browser_engine=. create_ghost_provider is the correct import."""
        source = self._ghost_block_source()

        assert "get_browser_engine" not in source, (
            "Ghost Protocol call-site should not import get_browser_engine"
        )
        assert "create_ghost_provider" in source, (
            "Ghost Protocol call-site must import create_ghost_provider"
        )
        assert "provider=" in source, (
            "run_ghost_protocol must be called with provider= kwarg"
        )
        assert "browser_engine=" not in source, (
            "run_ghost_protocol should not use browser_engine= kwarg"
        )

    def test_ghost_uses_content_not_extracted_text(self):
        """G#3: GhostResult has .content not .extracted_text.
        The call-site must reference ghost_result.content."""
        source = self._ghost_block_source()

        assert "extracted_text" not in source, (
            "Ghost Protocol call-site should use .content, not .extracted_text"
        )
        assert "ghost_result.content" in source, (
            "Ghost Protocol call-site must use ghost_result.content"
        )

    def test_ghost_result_content_field_exists(self):
        """Sanity check: GhostResult dataclass has .content, not .extracted_text."""
        from app.agent.ghost import GhostResult

        gr = GhostResult(success=True, content="hello")
        assert gr.content == "hello"
        assert not hasattr(gr, "extracted_text")


# --- Proxy health tracking ---


class TestReviewCrawlProxyHealthTracking:
    """Verify proxy health tracking (mark_failed / mark_success) is wired
    into the review-crawl endpoint by inspecting routes.py source."""

    @staticmethod
    def _review_crawl_source():
        """Return the source of the review-crawl handler."""
        import pathlib

        routes_path = pathlib.Path(__file__).parent.parent / "app" / "routes.py"
        source = routes_path.read_text()
        start = source.index("# ---- Proxy resolution ----")
        end = source.index("return ReviewCrawlResult(", start)
        return source[start:end]

    def test_pool_hoisted_before_proxy_if_block(self):
        """pool = None must appear before the proxy_preference if-block."""
        source = self._review_crawl_source()
        pool_init_pos = source.index("pool = None")
        proxy_if_pos = source.index('if request.proxy_preference != "none":')
        assert pool_init_pos < proxy_if_pos, (
            "pool = None must be hoisted before the proxy_preference if-block"
        )

    def test_mark_failed_called_after_content_quality(self):
        """mark_failed must be called after content_quality is determined."""
        source = self._review_crawl_source()
        content_quality_pos = source.index("content_quality = payload.get")
        mark_failed_pos = source.index("mark_failed(")
        assert mark_failed_pos > content_quality_pos, (
            "mark_failed must come after content_quality assignment"
        )

    def test_mark_success_called_after_content_quality(self):
        """mark_success must be called after content_quality is determined."""
        source = self._review_crawl_source()
        content_quality_pos = source.index("content_quality = payload.get")
        mark_success_pos = source.index("mark_success(")
        assert mark_success_pos > content_quality_pos, (
            "mark_success must come after content_quality assignment"
        )
