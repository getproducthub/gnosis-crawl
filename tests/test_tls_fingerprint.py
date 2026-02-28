"""Tests for TLS fingerprint handling: Sec-CH-UA header guards for Camoufox."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestSetRealisticHeadersCamoufox:
    """_set_realistic_headers() should skip Chrome-specific Sec-CH-UA* headers for Camoufox."""

    async def test_skips_sec_ch_ua_headers_when_camoufox_with_browserforge(self):
        """When engine is camoufox + browserforge available, Sec-CH-UA* headers are NOT set."""
        mock_page = AsyncMock()
        mock_headers = {
            'Accept': 'text/html',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Sec-CH-UA': '"Chromium";v="135"',
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
        }
        mock_gen_instance = MagicMock()
        mock_gen_instance.generate.return_value = mock_headers
        mock_header_gen = MagicMock(return_value=mock_gen_instance)

        with patch("app.browser.settings") as mock_settings, \
             patch("app.browser._HAS_BROWSERFORGE", True), \
             patch("app.browser.HeaderGenerator", mock_header_gen, create=True):
            mock_settings.browser_engine = "camoufox"

            from app.browser import BrowserEngine
            engine = BrowserEngine.__new__(BrowserEngine)
            engine.page = mock_page

            await engine._set_realistic_headers()

            set_headers_call = mock_page.set_extra_http_headers.call_args[0][0]
            # Sec-CH-UA* should be excluded
            for key in set_headers_call:
                assert not key.startswith('Sec-CH-UA'), f"Unexpected Chrome Client Hint header: {key}"
            # But other headers should still be present
            assert 'Accept' in set_headers_call
            assert 'Accept-Language' in set_headers_call
            assert 'Sec-Fetch-Dest' in set_headers_call

    async def test_includes_sec_ch_ua_headers_when_chromium_with_browserforge(self):
        """When engine is chromium + browserforge available, Sec-CH-UA* headers ARE set."""
        mock_page = AsyncMock()
        mock_headers = {
            'Accept': 'text/html',
            'Accept-Language': 'en-US,en;q=0.9',
            'Sec-CH-UA': '"Chromium";v="135"',
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'document',
        }
        mock_gen_instance = MagicMock()
        mock_gen_instance.generate.return_value = mock_headers
        mock_header_gen = MagicMock(return_value=mock_gen_instance)

        with patch("app.browser.settings") as mock_settings, \
             patch("app.browser._HAS_BROWSERFORGE", True), \
             patch("app.browser.HeaderGenerator", mock_header_gen, create=True):
            mock_settings.browser_engine = "chromium"

            from app.browser import BrowserEngine
            engine = BrowserEngine.__new__(BrowserEngine)
            engine.page = mock_page

            await engine._set_realistic_headers()

            set_headers_call = mock_page.set_extra_http_headers.call_args[0][0]
            assert 'Sec-CH-UA' in set_headers_call
            assert 'Sec-CH-UA-Mobile' in set_headers_call
            assert 'Sec-CH-UA-Platform' in set_headers_call

    async def test_skips_sec_ch_ua_in_static_fallback_when_camoufox(self):
        """When browserforge is NOT available and engine is camoufox, static headers skip Sec-CH-UA*."""
        mock_page = AsyncMock()

        with patch("app.browser.settings") as mock_settings, \
             patch("app.browser._HAS_BROWSERFORGE", False):
            mock_settings.browser_engine = "camoufox"

            from app.browser import BrowserEngine
            engine = BrowserEngine.__new__(BrowserEngine)
            engine.page = mock_page

            await engine._set_realistic_headers()

            set_headers_call = mock_page.set_extra_http_headers.call_args[0][0]
            for key in set_headers_call:
                assert not key.startswith('Sec-CH-UA'), f"Unexpected Chrome Client Hint header: {key}"
            # Sec-Fetch-* (non-CH) should still be present
            assert 'Accept-Language' in set_headers_call

    async def test_browserforge_uses_firefox_browser_for_camoufox(self):
        """When engine is camoufox, HeaderGenerator should be called with browser='firefox'."""
        mock_page = AsyncMock()
        mock_gen_instance = MagicMock()
        mock_gen_instance.generate.return_value = {'Accept': 'text/html'}
        mock_header_gen = MagicMock(return_value=mock_gen_instance)

        with patch("app.browser.settings") as mock_settings, \
             patch("app.browser._HAS_BROWSERFORGE", True), \
             patch("app.browser.HeaderGenerator", mock_header_gen, create=True):
            mock_settings.browser_engine = "camoufox"

            from app.browser import BrowserEngine
            engine = BrowserEngine.__new__(BrowserEngine)
            engine.page = mock_page

            await engine._set_realistic_headers()

            mock_header_gen.assert_called_once_with(browser='firefox')


class TestTlsImpersonateConfig:
    """Config should include tls_impersonate_chromium setting."""

    def test_tls_impersonate_chromium_defaults_false(self):
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.tls_impersonate_chromium is False

    def test_tls_impersonate_chromium_can_be_enabled(self):
        from app.config import Settings
        s = Settings(_env_file=None, tls_impersonate_chromium=True)
        assert s.tls_impersonate_chromium is True
