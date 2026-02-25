"""Tests for stealth module: apply_stealth, setup_request_interception."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestApplyStealth:
    async def test_calls_stealth_async_when_enabled(self):
        """apply_stealth() calls Stealth().apply_stealth_async when stealth is enabled."""
        mock_context = MagicMock()
        mock_apply = AsyncMock()
        mock_stealth_instance = MagicMock()
        mock_stealth_instance.apply_stealth_async = mock_apply
        mock_stealth_cls = MagicMock(return_value=mock_stealth_instance)

        with patch("app.stealth.settings") as mock_settings:
            mock_settings.stealth_enabled = True
            with patch.dict("sys.modules", {"playwright_stealth": MagicMock(Stealth=mock_stealth_cls)}):
                from app.stealth import apply_stealth
                await apply_stealth(mock_context)
                mock_stealth_cls.assert_called_once()
                mock_apply.assert_called_once_with(mock_context)

    async def test_noop_when_disabled(self):
        """apply_stealth() does nothing when stealth is disabled."""
        mock_context = MagicMock()

        with patch("app.stealth.settings") as mock_settings:
            mock_settings.stealth_enabled = False
            from app.stealth import apply_stealth
            await apply_stealth(mock_context)
            # No exception, no calls to stealth_async


@pytest.mark.asyncio
class TestSetupRequestInterception:
    async def test_registers_route_when_enabled(self):
        """setup_request_interception() registers a route handler when enabled."""
        mock_context = AsyncMock()

        with patch("app.stealth.settings") as mock_settings:
            mock_settings.block_tracking_domains = True
            from app.stealth import setup_request_interception
            await setup_request_interception(mock_context)
            mock_context.route.assert_called_once()
            # First arg should be "**/*"
            assert mock_context.route.call_args[0][0] == "**/*"

    async def test_noop_when_disabled(self):
        """setup_request_interception() does nothing when tracking blocking is disabled."""
        mock_context = AsyncMock()

        with patch("app.stealth.settings") as mock_settings:
            mock_settings.block_tracking_domains = False
            from app.stealth import setup_request_interception
            await setup_request_interception(mock_context)
            mock_context.route.assert_not_called()


class TestResolveProxy:
    def test_returns_none_when_no_config(self):
        """resolve_proxy() returns None when no proxy config anywhere."""
        mock_settings = MagicMock()
        mock_settings.get_proxy_config.return_value = None

        from app.proxy import resolve_proxy
        result = resolve_proxy(request_proxy=None, app_settings=mock_settings)
        assert result is None

    def test_returns_request_proxy_over_env_proxy(self):
        """Per-request proxy takes priority over env-based proxy."""
        mock_settings = MagicMock()
        mock_settings.get_proxy_config.return_value = {"server": "http://env-proxy:8080"}

        request_proxy = MagicMock()
        request_proxy.model_dump.return_value = {"server": "http://request-proxy:9090"}

        from app.proxy import resolve_proxy
        result = resolve_proxy(request_proxy=request_proxy, app_settings=mock_settings)
        assert result == {"server": "http://request-proxy:9090"}

    def test_falls_back_to_env_proxy(self):
        """Falls back to env proxy when no request proxy provided."""
        mock_settings = MagicMock()
        mock_settings.get_proxy_config.return_value = {"server": "http://env-proxy:8080"}

        from app.proxy import resolve_proxy
        result = resolve_proxy(request_proxy=None, app_settings=mock_settings)
        assert result == {"server": "http://env-proxy:8080"}
