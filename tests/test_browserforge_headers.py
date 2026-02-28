"""Tests for BrowserForge header integration and UA version updates.

WS3: Validates that:
- Fallback Chrome versions are updated to 133+ range (no more 128-132)
- Google referer is present in both browserforge and fallback paths
- BrowserForge generates Sec-CH-UA headers when available
- Graceful fallback when browserforge is not installed
- browser_pool.py UA is updated to Chrome/133+ (not stale Chrome/124)
"""

import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFallbackChromeVersions:
    """Fallback UA list must use Chrome 133+ versions (no 128-132)."""

    def test_no_stale_chrome_versions_in_fallback(self):
        """All Chrome versions in the fallback list must be >= 133."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()

        # Monkey-patch _HAS_BROWSERFORGE to False to force fallback path
        with patch("app.browser._HAS_BROWSERFORGE", False):
            # Generate many UAs to sample the full list
            uas = set()
            for _ in range(200):
                uas.add(engine._get_random_user_agent())

        for ua in uas:
            match = re.search(r"Chrome/(\d+)\.", ua)
            assert match, f"UA missing Chrome version: {ua}"
            major = int(match.group(1))
            assert major >= 133, (
                f"Stale Chrome version {major} found in fallback UA: {ua}"
            )

    def test_fallback_ua_format_is_valid(self):
        """Fallback UA must follow Mozilla/5.0 (...) AppleWebKit/... Chrome/... Safari/... format."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()

        with patch("app.browser._HAS_BROWSERFORGE", False):
            ua = engine._get_random_user_agent()

        assert ua.startswith("Mozilla/5.0 ("), f"Bad UA prefix: {ua}"
        assert "AppleWebKit/537.36" in ua
        assert "Chrome/" in ua
        assert "Safari/537.36" in ua


class TestGoogleReferer:
    """Google referer must be set in all header paths."""

    @pytest.mark.asyncio
    async def test_fallback_headers_include_google_referer(self):
        """Fallback (non-browserforge) path must include Google referer."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()
        mock_page = AsyncMock()
        engine.page = mock_page

        with patch("app.browser._HAS_BROWSERFORGE", False):
            await engine._set_realistic_headers()

        mock_page.set_extra_http_headers.assert_called_once()
        headers = mock_page.set_extra_http_headers.call_args[0][0]
        assert headers.get("Referer") == "https://www.google.com/", (
            f"Missing or wrong Referer in fallback headers: {headers}"
        )

    @pytest.mark.asyncio
    async def test_browserforge_headers_include_google_referer(self):
        """BrowserForge path must include Google referer."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()
        mock_page = AsyncMock()
        engine.page = mock_page

        # Mock browserforge to return realistic headers
        mock_generated = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/135.0.6972.61",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-CH-UA": '"Chromium";v="135", "Google Chrome";v="135"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        mock_gen_instance = MagicMock()
        mock_gen_instance.generate.return_value = mock_generated
        mock_header_gen = MagicMock(return_value=mock_gen_instance)

        with patch("app.browser._HAS_BROWSERFORGE", True), \
             patch("app.browser.HeaderGenerator", mock_header_gen, create=True):
            await engine._set_realistic_headers()

        mock_page.set_extra_http_headers.assert_called_once()
        headers = mock_page.set_extra_http_headers.call_args[0][0]
        assert headers.get("Referer") == "https://www.google.com/", (
            f"Missing Google referer in browserforge path: {headers}"
        )


class TestBrowserForgeSecChUa:
    """BrowserForge path must generate Sec-CH-UA headers."""

    @pytest.mark.asyncio
    async def test_sec_ch_ua_present_when_browserforge_available(self):
        """When browserforge is available, Sec-CH-UA headers should be in output."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()
        mock_page = AsyncMock()
        engine.page = mock_page

        mock_generated = {
            "User-Agent": "Mozilla/5.0 test",
            "Accept": "text/html",
            "Accept-Language": "en-US",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-CH-UA": '"Chromium";v="135", "Google Chrome";v="135"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        mock_gen_instance = MagicMock()
        mock_gen_instance.generate.return_value = mock_generated
        mock_header_gen = MagicMock(return_value=mock_gen_instance)

        with patch("app.browser._HAS_BROWSERFORGE", True), \
             patch("app.browser.HeaderGenerator", mock_header_gen, create=True):
            await engine._set_realistic_headers()

        headers = mock_page.set_extra_http_headers.call_args[0][0]
        assert "Sec-CH-UA" in headers, f"Missing Sec-CH-UA: {headers}"
        assert "Sec-CH-UA-Mobile" in headers, f"Missing Sec-CH-UA-Mobile: {headers}"
        assert "Sec-CH-UA-Platform" in headers, f"Missing Sec-CH-UA-Platform: {headers}"


class TestBrowserForgeFallback:
    """Graceful fallback when browserforge is not installed."""

    def test_fallback_ua_works_without_browserforge(self):
        """_get_random_user_agent works even when _HAS_BROWSERFORGE is False."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()

        with patch("app.browser._HAS_BROWSERFORGE", False):
            ua = engine._get_random_user_agent()

        assert isinstance(ua, str)
        assert "Chrome/" in ua
        assert len(ua) > 50

    @pytest.mark.asyncio
    async def test_fallback_headers_work_without_browserforge(self):
        """_set_realistic_headers works even when _HAS_BROWSERFORGE is False."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()
        mock_page = AsyncMock()
        engine.page = mock_page

        with patch("app.browser._HAS_BROWSERFORGE", False):
            await engine._set_realistic_headers()

        mock_page.set_extra_http_headers.assert_called_once()
        headers = mock_page.set_extra_http_headers.call_args[0][0]
        # Core headers must still be present
        assert "Accept-Language" in headers
        assert "Accept" in headers
        assert "Sec-Fetch-Dest" in headers

    def test_browserforge_exception_falls_through_to_manual_ua(self):
        """If browserforge raises an exception, fallback UA is used."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()

        mock_gen_instance = MagicMock()
        mock_gen_instance.generate.side_effect = RuntimeError("browserforge broken")
        mock_header_gen = MagicMock(return_value=mock_gen_instance)

        with patch("app.browser._HAS_BROWSERFORGE", True), \
             patch("app.browser.HeaderGenerator", mock_header_gen, create=True):
            ua = engine._get_random_user_agent()

        assert isinstance(ua, str)
        assert "Chrome/" in ua
        # Should be from the updated fallback list (133+)
        match = re.search(r"Chrome/(\d+)\.", ua)
        assert match and int(match.group(1)) >= 133

    @pytest.mark.asyncio
    async def test_browserforge_header_exception_falls_through(self):
        """If browserforge raises in _set_realistic_headers, fallback headers are used."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()
        mock_page = AsyncMock()
        engine.page = mock_page

        mock_gen_instance = MagicMock()
        mock_gen_instance.generate.side_effect = RuntimeError("browserforge broken")
        mock_header_gen = MagicMock(return_value=mock_gen_instance)

        with patch("app.browser._HAS_BROWSERFORGE", True), \
             patch("app.browser.HeaderGenerator", mock_header_gen, create=True):
            await engine._set_realistic_headers()

        headers = mock_page.set_extra_http_headers.call_args[0][0]
        assert "Accept-Language" in headers
        assert headers.get("Referer") == "https://www.google.com/"


class TestBrowserPoolUAUpdate:
    """browser_pool.py must use Chrome 133+ UA, not stale Chrome/124."""

    def test_pool_ua_not_chrome_124(self):
        """The hardcoded UA in browser_pool.py must not be Chrome/124."""
        import app.browser_pool as bp
        import inspect

        source = inspect.getsource(bp.BrowserPool._create_slot)
        assert "Chrome/124" not in source, (
            "browser_pool.py still contains stale Chrome/124 UA string"
        )

    def test_pool_ua_is_chrome_133_or_higher(self):
        """The hardcoded UA in browser_pool.py must use Chrome >= 133."""
        import app.browser_pool as bp
        import inspect

        source = inspect.getsource(bp.BrowserPool._create_slot)
        match = re.search(r"Chrome/(\d+)\.", source)
        assert match, "No Chrome/NNN pattern found in _create_slot source"
        major = int(match.group(1))
        assert major >= 133, (
            f"browser_pool.py uses Chrome/{major}, expected >= 133"
        )
