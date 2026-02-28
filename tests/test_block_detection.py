"""
Tests for _detect_block_signals in CrawlerEngine.

Verifies that block phrases (e.g. "just a moment", "cloudflare") in HTML/markdown
do NOT trigger a false-positive block when the page has real content.

Capterra pages with ~9K HTML commonly include Cloudflare challenge boilerplate
in headers/scripts even when successfully loaded. The substantial-content guard
must prevent false positives.

Created: 2026-02-27
"""

import pytest
from unittest.mock import MagicMock
from app.crawler import CrawlerEngine


@pytest.fixture
def handler():
    """Create a minimal CrawlerEngine for unit-testing _detect_block_signals."""
    return CrawlerEngine.__new__(CrawlerEngine)


class TestDetectBlockSignals:
    """Block detection with substantial-content guard."""

    def test_small_challenge_page_is_blocked(self, handler):
        """A small page with 'just a moment' is a real challenge — should be blocked."""
        html = "<html><head><title>Just a moment...</title></head><body>Please wait</body></html>"
        blocked, reason, captcha = handler._detect_block_signals(html, "", None)
        assert blocked is True
        assert reason == "bot_challenge"

    def test_small_cloudflare_page_is_blocked(self, handler):
        """A small page with 'cloudflare' is a real challenge."""
        html = "<html><body>Checking your browser... Cloudflare</body></html>"
        blocked, reason, captcha = handler._detect_block_signals(html, "", None)
        assert blocked is True
        assert reason == "cloudflare_challenge"

    def test_large_html_with_challenge_phrase_not_blocked(self, handler):
        """A page with >10K HTML containing 'cloudflare' in scripts is NOT blocked."""
        # Simulate a real review page with Cloudflare script references in boilerplate
        real_content = "Great product review. " * 500  # ~10K chars
        html = f"<html><head><script src='cloudflare-cdn.js'></script></head><body>{real_content}</body></html>"
        assert len(html) > 10000

        blocked, reason, captcha = handler._detect_block_signals(html, "", None)
        assert blocked is False

    def test_moderate_html_with_rich_markdown_not_blocked(self, handler):
        """9K HTML + 3K markdown with 'just a moment' in header is NOT blocked.

        This is the Capterra false positive scenario: the page loaded fine (~9K HTML),
        markdown extraction produced real content (>2K), but the HTML header
        contains 'just a moment' from Cloudflare's initial challenge.
        """
        # Capterra-like HTML: under 10K but has real content
        html = "<html><head><title>Just a moment</title></head><body>" + "Review text. " * 600 + "</body></html>"
        assert len(html) < 10000

        # Markdown extraction produced real review content
        markdown = "# Dovetail Reviews\n\n" + "Great product for user research. " * 80
        assert len(markdown) > 2000

        blocked, reason, captcha = handler._detect_block_signals(html, markdown, None)
        assert blocked is False

    def test_small_html_with_short_markdown_is_blocked(self, handler):
        """Small HTML (<5K) + tiny markdown with 'just a moment' IS blocked.

        If HTML is under 5K AND markdown is under threshold, the page
        is likely a real challenge/block page.
        """
        html = "<html><head><title>Just a moment</title></head><body>" + "x" * 3000 + "</body></html>"
        assert len(html) < 5000

        # Very short markdown = page didn't render properly
        markdown = "Loading..."
        assert len(markdown) < 500

        blocked, reason, captcha = handler._detect_block_signals(html, markdown, None)
        assert blocked is True

    def test_403_with_substantial_content_not_blocked(self, handler):
        """HTTP 403 with large content is a soft-block — should not be flagged."""
        html = "x" * 15000
        blocked, reason, captcha = handler._detect_block_signals(html, "", 403)
        assert blocked is False

    def test_403_without_content_is_blocked(self, handler):
        """HTTP 403 with no content is a hard block."""
        blocked, reason, captcha = handler._detect_block_signals("", "", 403)
        assert blocked is True
        assert reason == "http_403"

    def test_captcha_detection(self, handler):
        """Pages with 'captcha' should set captcha_detected=True."""
        html = "<html><body>Please solve this captcha to continue</body></html>"
        blocked, reason, captcha = handler._detect_block_signals(html, "", None)
        assert blocked is True
        assert captcha is True

    def test_clean_page_not_blocked(self, handler):
        """A normal page with no challenge phrases is not blocked."""
        html = "<html><body>Welcome to our product reviews</body></html>"
        blocked, reason, captcha = handler._detect_block_signals(html, "", 200)
        assert blocked is False
