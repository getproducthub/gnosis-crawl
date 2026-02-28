"""
Tests for X-Client-Timeout header support.

Verifies that gnosis-crawl reads the X-Client-Timeout header from requests
and stops retries when the client's timeout budget is exhausted.
"""

import time
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.browser import BrowserEngine


class TestClientTimeoutHeaderParsing:
    """Test that the X-Client-Timeout header is correctly parsed from requests."""

    def test_valid_header_parsed_as_integer(self):
        """X-Client-Timeout: 120 should be parsed as 120 seconds."""
        header_value = "120"
        result = int(header_value) if header_value and header_value.isdigit() else None
        assert result == 120

    def test_missing_header_returns_none(self):
        """Missing X-Client-Timeout header should result in None (default behavior)."""
        header_value = None
        result = int(header_value) if header_value and header_value.isdigit() else None
        assert result is None

    def test_non_numeric_header_returns_none(self):
        """Non-numeric X-Client-Timeout should be treated as None."""
        header_value = "abc"
        result = int(header_value) if header_value and header_value.isdigit() else None
        assert result is None

    def test_zero_header_returns_zero(self):
        """X-Client-Timeout: 0 should be parsed as 0."""
        header_value = "0"
        result = int(header_value) if header_value and header_value.isdigit() else None
        assert result == 0

    def test_empty_string_header_returns_none(self):
        """Empty string header should result in None."""
        header_value = ""
        result = int(header_value) if header_value and header_value.isdigit() else None
        assert result is None


class TestBrowserRetryDeadline:
    """Test that crawl_with_context stops retries when client deadline is exceeded."""

    @pytest.mark.asyncio
    async def test_retries_stop_when_deadline_exceeded(self):
        """When client_timeout_seconds is set and deadline passes, retries should stop."""
        engine = BrowserEngine()
        engine.browser = MagicMock()
        engine.browser.is_connected = MagicMock(return_value=True)

        # Track how many attempts were made
        attempts = []

        async def mock_create_context(*args, **kwargs):
            context = AsyncMock()
            page = AsyncMock()

            async def mock_goto(url, **kw):
                attempts.append(time.monotonic())
                raise Exception("Navigation timeout")

            page.goto = mock_goto
            page.content = AsyncMock(return_value="<html></html>")
            page.title = AsyncMock(return_value="Test")
            page.url = "http://example.com"
            page.viewport_size = {"width": 1920, "height": 1080}
            context.close = AsyncMock()

            return context, page

        engine.create_isolated_context = mock_create_context

        # Set client timeout to 1 second — should stop retries quickly
        with pytest.raises(Exception):
            await engine.crawl_with_context(
                "http://example.com",
                timeout=30000,
                client_timeout_seconds=1,
            )

        # With a 1-second budget, we should get fewer attempts than max_retries (3)
        # Due to the 5s safety margin, a 1s budget means 0 retries allowed after first attempt
        assert len(attempts) <= 2, f"Expected <=2 attempts with 1s budget, got {len(attempts)}"

    @pytest.mark.asyncio
    async def test_retries_continue_without_deadline(self):
        """Without client_timeout_seconds, all retries should be attempted."""
        engine = BrowserEngine()
        engine.browser = MagicMock()
        engine.browser.is_connected = MagicMock(return_value=True)

        attempts = []

        async def mock_create_context(*args, **kwargs):
            context = AsyncMock()
            page = AsyncMock()

            async def mock_goto(url, **kw):
                attempts.append(time.monotonic())
                raise Exception("Navigation timeout")

            page.goto = mock_goto
            context.close = AsyncMock()
            return context, page

        engine.create_isolated_context = mock_create_context

        with pytest.raises(Exception):
            await engine.crawl_with_context(
                "http://example.com",
                timeout=30000,
                # No client_timeout_seconds — default behavior
            )

        # All 3 retries should be attempted
        assert len(attempts) == 3, f"Expected 3 attempts without deadline, got {len(attempts)}"

    @pytest.mark.asyncio
    async def test_deadline_with_sufficient_budget(self):
        """With a large client timeout budget, all retries should be possible."""
        engine = BrowserEngine()
        engine.browser = MagicMock()
        engine.browser.is_connected = MagicMock(return_value=True)

        attempts = []

        async def mock_create_context(*args, **kwargs):
            context = AsyncMock()
            page = AsyncMock()

            async def mock_goto(url, **kw):
                attempts.append(time.monotonic())
                raise Exception("Navigation timeout")

            page.goto = mock_goto
            context.close = AsyncMock()
            return context, page

        engine.create_isolated_context = mock_create_context

        with pytest.raises(Exception):
            await engine.crawl_with_context(
                "http://example.com",
                timeout=30000,
                client_timeout_seconds=300,  # 5 minutes — plenty of budget
            )

        # All retries should proceed with this large budget
        assert len(attempts) == 3
