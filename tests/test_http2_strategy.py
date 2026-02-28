"""Tests for HTTP/2 strategy: usable_content field, Camoufox HTTP/2 config."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestPrecheckResultUsableContent:
    """PrecheckResult should have a usable_content field."""

    def test_usable_content_defaults_none(self):
        from app.http_precheck import PrecheckResult
        result = PrecheckResult()
        assert result.usable_content is None

    def test_usable_content_can_be_set(self):
        from app.http_precheck import PrecheckResult
        result = PrecheckResult(usable_content="# Heading\nSome content")
        assert result.usable_content == "# Heading\nSome content"


@pytest.mark.asyncio
class TestPrecheckUsableContentPopulation:
    """http_precheck should populate usable_content when browser is not needed."""

    async def test_usable_content_set_when_no_browser_needed(self):
        """When needs_browser=False and content > 1024 chars, usable_content is set."""
        content = "<html><body>" + "Real article content. " * 200 + "</body></html>"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = content
        mock_response.headers = {"content-type": "text/html"}

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.http_precheck._HAS_CURL_CFFI", True), \
             patch("app.http_precheck.settings") as mock_settings, \
             patch("app.http_precheck.AsyncSession", return_value=mock_session, create=True):
            mock_settings.http_precheck_enabled = True
            mock_settings.http_precheck_timeout = 15
            mock_settings.http_precheck_impersonate = "chrome135"

            from app.http_precheck import http_precheck
            result = await http_precheck("https://example.com")

            assert result.success is True
            assert result.needs_browser is False
            assert result.usable_content is not None
            assert len(result.usable_content) > 1024

    async def test_usable_content_not_set_when_browser_needed(self):
        """When needs_browser=True, usable_content stays None."""
        content = "<html><body>cf-browser-verification" + "x" * 2000 + "</body></html>"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = content
        mock_response.headers = {}

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.http_precheck._HAS_CURL_CFFI", True), \
             patch("app.http_precheck.settings") as mock_settings, \
             patch("app.http_precheck.AsyncSession", return_value=mock_session, create=True):
            mock_settings.http_precheck_enabled = True
            mock_settings.http_precheck_timeout = 15
            mock_settings.http_precheck_impersonate = "chrome135"

            from app.http_precheck import http_precheck
            result = await http_precheck("https://protected-site.com")

            assert result.success is True
            assert result.needs_browser is True
            assert result.usable_content is None

    async def test_usable_content_not_set_when_content_short(self):
        """When content <= 1024, usable_content stays None even if needs_browser=False."""
        # Content at exactly 1024 chars (threshold for _check_needs_browser) but
        # with a 200 status and no markers -> needs_browser=False, but too short for usable
        content = "a" * 1024
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = content
        mock_response.headers = {}

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.http_precheck._HAS_CURL_CFFI", True), \
             patch("app.http_precheck.settings") as mock_settings, \
             patch("app.http_precheck.AsyncSession", return_value=mock_session, create=True):
            mock_settings.http_precheck_enabled = True
            mock_settings.http_precheck_timeout = 15
            mock_settings.http_precheck_impersonate = "chrome135"

            from app.http_precheck import http_precheck
            result = await http_precheck("https://example.com")

            assert result.success is True
            assert result.needs_browser is False
            assert result.usable_content is None


class TestCamoufoxHttp2Config:
    """Camoufox uses Firefox's real HTTP/2 stack — no custom config needed.

    The HTTP/2 gap is addressed by curl_cffi content-first strategy (usable_content),
    not by tuning Camoufox internals. Camoufox validates config keys strictly and
    rejects unknown Firefox about:config prefs.
    """

    def test_camoufox_launch_does_not_set_invalid_http2_config(self):
        """AsyncCamoufox launch must NOT pass unknown config keys that cause crashes."""
        import inspect
        from app.browser import BrowserEngine as BE
        source = inspect.getsource(BE.start_browser)
        assert "network.http.http2.default-concurrent" not in source, \
            "Camoufox rejects this config key — use curl_cffi content-first strategy instead"
