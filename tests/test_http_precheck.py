"""Tests for HTTP pre-check module: PrecheckResult, _check_needs_browser, http_precheck."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock


class TestPrecheckResultDefaults:
    """PrecheckResult dataclass should have safe defaults."""

    def test_needs_browser_defaults_true(self):
        from app.http_precheck import PrecheckResult
        result = PrecheckResult()
        assert result.needs_browser is True

    def test_success_defaults_false(self):
        from app.http_precheck import PrecheckResult
        result = PrecheckResult()
        assert result.success is False

    def test_url_defaults_empty(self):
        from app.http_precheck import PrecheckResult
        result = PrecheckResult()
        assert result.url == ""

    def test_status_code_defaults_none(self):
        from app.http_precheck import PrecheckResult
        result = PrecheckResult()
        assert result.status_code is None

    def test_content_defaults_empty(self):
        from app.http_precheck import PrecheckResult
        result = PrecheckResult()
        assert result.content == ""

    def test_content_length_defaults_zero(self):
        from app.http_precheck import PrecheckResult
        result = PrecheckResult()
        assert result.content_length == 0

    def test_headers_defaults_empty_dict(self):
        from app.http_precheck import PrecheckResult
        result = PrecheckResult()
        assert result.headers == {}

    def test_error_defaults_none(self):
        from app.http_precheck import PrecheckResult
        result = PrecheckResult()
        assert result.error is None


class TestCheckNeedsBrowser:
    """Heuristic function for deciding if a full browser is needed."""

    def test_returns_true_for_403(self):
        from app.http_precheck import _check_needs_browser
        assert _check_needs_browser(403, "some content" * 200, 2400) is True

    def test_returns_true_for_503(self):
        from app.http_precheck import _check_needs_browser
        assert _check_needs_browser(503, "some content" * 200, 2400) is True

    def test_returns_true_for_short_content(self):
        from app.http_precheck import _check_needs_browser
        assert _check_needs_browser(200, "short", 5) is True

    def test_returns_true_for_content_just_below_threshold(self):
        from app.http_precheck import _check_needs_browser
        content = "a" * 1023
        assert _check_needs_browser(200, content, 1023) is True

    def test_returns_false_for_content_at_threshold(self):
        from app.http_precheck import _check_needs_browser
        content = "a" * 1024
        assert _check_needs_browser(200, content, 1024) is False

    def test_returns_true_for_cf_challenge_marker(self):
        from app.http_precheck import _check_needs_browser
        content = "<html><body>cf-browser-verification required</body></html>" + "x" * 2000
        assert _check_needs_browser(200, content, len(content)) is True

    def test_returns_true_for_managed_challenge(self):
        from app.http_precheck import _check_needs_browser
        content = "<html><body>managed-challenge active</body></html>" + "x" * 2000
        assert _check_needs_browser(200, content, len(content)) is True

    def test_returns_true_for_noscript_tag(self):
        from app.http_precheck import _check_needs_browser
        content = "<html><body><noscript>Enable JS</noscript></body></html>" + "x" * 2000
        assert _check_needs_browser(200, content, len(content)) is True

    def test_returns_true_for_enable_javascript(self):
        from app.http_precheck import _check_needs_browser
        content = "<html><body>Please enable javascript to continue</body></html>" + "x" * 2000
        assert _check_needs_browser(200, content, len(content)) is True

    def test_returns_true_for_ddos_guard(self):
        from app.http_precheck import _check_needs_browser
        content = "<html><body>Protected by DDoS-Guard</body></html>" + "x" * 2000
        assert _check_needs_browser(200, content, len(content)) is True

    def test_returns_true_for_datadome(self):
        from app.http_precheck import _check_needs_browser
        content = "<html><body>DataDome challenge</body></html>" + "x" * 2000
        assert _check_needs_browser(200, content, len(content)) is True

    def test_returns_false_for_normal_200_with_sufficient_content(self):
        from app.http_precheck import _check_needs_browser
        content = "<html><body><p>This is a normal page with plenty of content. " + "x" * 3000 + "</p></body></html>"
        assert _check_needs_browser(200, content, len(content)) is False

    def test_marker_detection_is_case_insensitive(self):
        from app.http_precheck import _check_needs_browser
        content = "<html><body>CF-BROWSER-VERIFICATION required</body></html>" + "x" * 2000
        assert _check_needs_browser(200, content, len(content)) is True

    def test_only_scans_first_5000_chars(self):
        """Markers beyond 5000 chars should not be detected (performance guard)."""
        from app.http_precheck import _check_needs_browser
        # Place marker after 5000 chars
        content = "x" * 5001 + "cf-browser-verification"
        assert _check_needs_browser(200, content, len(content)) is False


@pytest.mark.asyncio
class TestHttpPrecheckDisabled:
    """http_precheck respects the settings.http_precheck_enabled flag."""

    async def test_returns_error_when_disabled(self):
        with patch("app.http_precheck.settings") as mock_settings:
            mock_settings.http_precheck_enabled = False
            # Ensure _HAS_CURL_CFFI is True so we actually hit the enabled check
            with patch("app.http_precheck._HAS_CURL_CFFI", True):
                from app.http_precheck import http_precheck
                result = await http_precheck("https://example.com")
                assert result.success is False
                assert result.needs_browser is True
                assert result.error == "precheck disabled"


@pytest.mark.asyncio
class TestHttpPrecheckNoCurlCffi:
    """http_precheck handles missing curl_cffi gracefully."""

    async def test_returns_error_when_curl_cffi_missing(self):
        with patch("app.http_precheck._HAS_CURL_CFFI", False):
            from app.http_precheck import http_precheck
            result = await http_precheck("https://example.com")
            assert result.success is False
            assert result.needs_browser is True
            assert result.error == "curl_cffi not installed"


@pytest.mark.asyncio
class TestHttpPrecheckSuccess:
    """http_precheck with mocked AsyncSession for successful requests."""

    async def test_successful_precheck_sets_fields(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>" + "Real content here. " * 200 + "</body></html>"
        mock_response.headers = {"content-type": "text/html", "server": "nginx"}

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
            assert result.status_code == 200
            assert result.content_length > 1024
            assert result.needs_browser is False
            assert result.error is None

    async def test_successful_precheck_with_challenge_page(self):
        """Even a 200 with CF markers should indicate needs_browser=True."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>cf-browser-verification challenge-platform" + "x" * 2000 + "</body></html>"
        mock_response.headers = {"server": "cloudflare"}

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

    async def test_precheck_network_error_fails_safe(self):
        """Network errors should result in needs_browser=True (fail-safe)."""
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(side_effect=ConnectionError("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.http_precheck._HAS_CURL_CFFI", True), \
             patch("app.http_precheck.settings") as mock_settings, \
             patch("app.http_precheck.AsyncSession", return_value=mock_session, create=True):
            mock_settings.http_precheck_enabled = True
            mock_settings.http_precheck_timeout = 15
            mock_settings.http_precheck_impersonate = "chrome135"

            from app.http_precheck import http_precheck
            result = await http_precheck("https://unreachable.com")

            assert result.success is False
            assert result.needs_browser is True
            assert "Connection refused" in result.error

    async def test_precheck_uses_custom_timeout_and_impersonate(self):
        """http_precheck passes custom timeout and impersonate to session."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "x" * 2000
        mock_response.headers = {}

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.http_precheck._HAS_CURL_CFFI", True), \
             patch("app.http_precheck.settings") as mock_settings, \
             patch("app.http_precheck.AsyncSession", return_value=mock_session, create=True) as mock_session_cls:
            mock_settings.http_precheck_enabled = True
            mock_settings.http_precheck_timeout = 15
            mock_settings.http_precheck_impersonate = "chrome135"

            from app.http_precheck import http_precheck
            result = await http_precheck("https://example.com", timeout=30, impersonate="chrome131")

            # AsyncSession should have been created with the custom impersonate
            mock_session_cls.assert_called_once_with(impersonate="chrome131")
            # get should have been called with the custom timeout
            call_kwargs = mock_session.get.call_args[1]
            assert call_kwargs["timeout"] == 30


class TestConfigSettings:
    """Config should include the new HTTP pre-check settings."""

    def test_http_precheck_enabled_default(self):
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.http_precheck_enabled is False

    def test_http_precheck_timeout_default(self):
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.http_precheck_timeout == 15

    def test_http_precheck_impersonate_default(self):
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.http_precheck_impersonate == "chrome135"
