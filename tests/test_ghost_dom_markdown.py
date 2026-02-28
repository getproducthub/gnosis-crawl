"""Tests for Ghost Protocol DOM markdown extraction preference.

Verifies that:
1. GhostCapture has html and dom_markdown fields
2. run_ghost_protocol returns render_mode="ghost_dom" when DOM markdown is sufficient
3. Blocked DOM markdown falls through to vision extraction
4. Short/empty DOM markdown falls through to vision extraction
"""

import time
from dataclasses import fields as dataclass_fields
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.ghost import GhostCapture, GhostResult


class TestGhostCaptureFields:
    """GhostCapture dataclass must include html and dom_markdown fields."""

    def test_has_html_field(self):
        capture = GhostCapture(success=True)
        assert hasattr(capture, "html"), "GhostCapture must have an 'html' field"

    def test_has_dom_markdown_field(self):
        capture = GhostCapture(success=True)
        assert hasattr(capture, "dom_markdown"), "GhostCapture must have a 'dom_markdown' field"

    def test_html_defaults_to_empty_string(self):
        capture = GhostCapture(success=True)
        assert capture.html == ""

    def test_dom_markdown_defaults_to_empty_string(self):
        capture = GhostCapture(success=True)
        assert capture.dom_markdown == ""

    def test_fields_accept_values(self):
        capture = GhostCapture(
            success=True,
            html="<html><body>Hello</body></html>",
            dom_markdown="# Hello",
        )
        assert capture.html == "<html><body>Hello</body></html>"
        assert capture.dom_markdown == "# Hello"


@pytest.mark.asyncio
class TestDomMarkdownSufficient:
    """When DOM markdown is >200 chars and not blocked, run_ghost_protocol
    should return early with render_mode='ghost_dom' and skip vision."""

    async def test_returns_ghost_dom_render_mode(self):
        """Sufficient, non-blocked DOM markdown triggers ghost_dom path."""
        good_markdown = "# Product Reviews\n\n" + ("Great product. " * 30)
        assert len(good_markdown.strip()) > 200

        mock_capture = GhostCapture(
            success=True,
            image_bytes=b"fake-png",
            url="https://g2.com/reviews",
            capture_ms=500,
            html="<html><body>content</body></html>",
            dom_markdown=good_markdown,
        )

        with patch("app.agent.ghost.capture_screenshot", new_callable=AsyncMock) as mock_ss, \
             patch("app.agent.ghost.extract_via_vision", new_callable=AsyncMock) as mock_vision:
            mock_ss.return_value = mock_capture

            from app.agent.ghost import run_ghost_protocol
            result = await run_ghost_protocol(url="https://g2.com/reviews")

            assert result.success is True
            assert result.render_mode == "ghost_dom"
            assert result.provider == "dom_markdown"
            assert result.content == good_markdown
            # Vision should NOT have been called
            mock_vision.assert_not_called()

    async def test_ghost_dom_includes_capture_ms(self):
        """ghost_dom result should carry the capture_ms from screenshot."""
        good_markdown = "# Reviews\n" + ("Excellent service. " * 20)

        mock_capture = GhostCapture(
            success=True,
            image_bytes=b"fake-png",
            url="https://g2.com/reviews",
            capture_ms=750,
            html="<html>x</html>",
            dom_markdown=good_markdown,
        )

        with patch("app.agent.ghost.capture_screenshot", new_callable=AsyncMock) as mock_ss, \
             patch("app.agent.ghost.extract_via_vision", new_callable=AsyncMock):
            mock_ss.return_value = mock_capture

            from app.agent.ghost import run_ghost_protocol
            result = await run_ghost_protocol(url="https://g2.com/reviews")

            assert result.capture_ms == 750


@pytest.mark.asyncio
class TestDomMarkdownBlocked:
    """When DOM markdown is blocked (detect_block returns blocked=True),
    it should fall through to vision extraction."""

    async def test_blocked_dom_falls_through_to_vision(self):
        """Blocked DOM markdown must not short-circuit; vision is called."""
        blocked_md = "Just a moment... Checking your browser. " * 10
        assert len(blocked_md.strip()) > 200

        mock_capture = GhostCapture(
            success=True,
            image_bytes=b"fake-png",
            url="https://g2.com/reviews",
            capture_ms=400,
            html="<html>blocked</html>",
            dom_markdown=blocked_md,
        )

        from app.agent.ghost import GhostExtraction
        mock_extraction = GhostExtraction(
            success=True,
            content="# Actual content from vision",
            extraction_ms=2000,
            provider="openai",
        )

        with patch("app.agent.ghost.capture_screenshot", new_callable=AsyncMock) as mock_ss, \
             patch("app.agent.ghost.extract_via_vision", new_callable=AsyncMock) as mock_vision:
            mock_ss.return_value = mock_capture
            mock_vision.return_value = mock_extraction

            from app.agent.ghost import run_ghost_protocol
            result = await run_ghost_protocol(url="https://g2.com/reviews")

            # Vision must have been called since DOM was blocked
            mock_vision.assert_called_once()
            assert result.render_mode == "ghost"


@pytest.mark.asyncio
class TestDomMarkdownTooShort:
    """When DOM markdown is too short (<= 200 chars) or empty,
    it should fall through to vision extraction."""

    async def test_empty_dom_falls_through(self):
        """Empty dom_markdown should fall through to vision."""
        mock_capture = GhostCapture(
            success=True,
            image_bytes=b"fake-png",
            url="https://g2.com/reviews",
            capture_ms=300,
            html="<html>empty</html>",
            dom_markdown="",
        )

        from app.agent.ghost import GhostExtraction
        mock_extraction = GhostExtraction(
            success=True,
            content="# Vision content",
            extraction_ms=1500,
            provider="openai",
        )

        with patch("app.agent.ghost.capture_screenshot", new_callable=AsyncMock) as mock_ss, \
             patch("app.agent.ghost.extract_via_vision", new_callable=AsyncMock) as mock_vision:
            mock_ss.return_value = mock_capture
            mock_vision.return_value = mock_extraction

            from app.agent.ghost import run_ghost_protocol
            result = await run_ghost_protocol(url="https://g2.com/reviews")

            mock_vision.assert_called_once()

    async def test_short_dom_falls_through(self):
        """DOM markdown of <= 200 chars should fall through to vision."""
        short_md = "# Reviews\nShort page."
        assert len(short_md.strip()) <= 200

        mock_capture = GhostCapture(
            success=True,
            image_bytes=b"fake-png",
            url="https://g2.com/reviews",
            capture_ms=300,
            html="<html>short</html>",
            dom_markdown=short_md,
        )

        from app.agent.ghost import GhostExtraction
        mock_extraction = GhostExtraction(
            success=True,
            content="# Vision content with more detail",
            extraction_ms=1800,
            provider="openai",
        )

        with patch("app.agent.ghost.capture_screenshot", new_callable=AsyncMock) as mock_ss, \
             patch("app.agent.ghost.extract_via_vision", new_callable=AsyncMock) as mock_vision:
            mock_ss.return_value = mock_capture
            mock_vision.return_value = mock_extraction

            from app.agent.ghost import run_ghost_protocol
            result = await run_ghost_protocol(url="https://g2.com/reviews")

            mock_vision.assert_called_once()
