"""Tests for Settings.get_proxy_config()."""

import pytest
from unittest.mock import patch


class TestGetProxyConfig:
    def test_returns_none_when_no_proxy_env_vars(self):
        """No proxy env vars => None."""
        from app.config import Settings

        s = Settings(proxy_server=None)
        assert s.get_proxy_config() is None

    def test_returns_dict_with_just_server(self):
        """Only PROXY_SERVER set => dict with 'server' key only."""
        from app.config import Settings

        s = Settings(proxy_server="http://gate.decodo.com:10001", proxy_username=None, proxy_password=None)
        result = s.get_proxy_config()
        assert result is not None
        assert result["server"] == "http://gate.decodo.com:10001"
        assert "username" not in result
        assert "password" not in result

    def test_returns_full_dict_when_all_vars_set(self):
        """All proxy vars set => full Playwright-compatible dict."""
        from app.config import Settings

        s = Settings(
            proxy_server="http://gate.decodo.com:10001",
            proxy_username="spwod13p0r",
            proxy_password="19It6za6vHpFTj_bzg",
        )
        result = s.get_proxy_config()
        assert result is not None
        assert result["server"] == "http://gate.decodo.com:10001"
        assert result["username"] == "spwod13p0r"
        assert result["password"] == "19It6za6vHpFTj_bzg"

    def test_bypass_included_when_set(self):
        """Bypass field included when non-empty."""
        from app.config import Settings

        s = Settings(
            proxy_server="http://gate.decodo.com:10001",
            proxy_bypass="localhost,127.0.0.1",
        )
        result = s.get_proxy_config()
        assert result is not None
        assert result["bypass"] == "localhost,127.0.0.1"
