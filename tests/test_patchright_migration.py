"""Tests for WS1: Patchright migration + CDP leak fix.

Validates:
- patchright is used for Chromium path when available
- Camoufox path is unchanged (still uses playwright internals)
- Graceful fallback to playwright when patchright not installed
- --disable-web-security is NOT in browser args
- --disable-blink-features=AutomationControlled IS in browser args
- BrowserPool uses patchright for Chromium launch
"""

import importlib
import os
import pytest
import sys
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_settings(**overrides):
    """Create a mock settings object with sensible defaults."""
    s = MagicMock()
    s.browser_engine = overrides.get("browser_engine", "chromium")
    s.browser_headless = overrides.get("browser_headless", True)
    s.max_concurrent_crawls = overrides.get("max_concurrent_crawls", 4)
    s.browser_stream_max_width = overrides.get("browser_stream_max_width", 1280)
    s.browser_pool_size = overrides.get("browser_pool_size", 1)
    s.browser_stream_max_lease_seconds = overrides.get("browser_stream_max_lease_seconds", 300)
    s.stealth_enabled = overrides.get("stealth_enabled", False)
    s.block_tracking_domains = overrides.get("block_tracking_domains", False)
    s.get_proxy_config.return_value = None
    return s


def _fresh_import(module_name, mock_settings):
    """Force a fresh import of a module with mocked settings.

    Removes the module (and app.config) from sys.modules cache, patches
    app.config.settings, then re-imports so the module picks up our mock.
    """
    # Remove cached modules so re-import is clean
    for key in list(sys.modules.keys()):
        if key == module_name or key == "app.config":
            del sys.modules[key]

    # Inject a fake app.config with our mock settings
    fake_config = MagicMock()
    fake_config.settings = mock_settings
    sys.modules["app.config"] = fake_config

    mod = importlib.import_module(module_name)
    return mod


# ---------------------------------------------------------------------------
# browser.py tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBrowserEnginePatchright:
    """BrowserEngine should use patchright for Chromium when available."""

    async def test_chromium_uses_patchright_when_available(self):
        """When _HAS_PATCHRIGHT is True, start_browser uses async_patchright."""
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.is_connected.return_value = True
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_patchright_start = AsyncMock(return_value=mock_pw)
        mock_patchright_cm = MagicMock()
        mock_patchright_cm.start = mock_patchright_start

        mock_settings = _make_mock_settings(browser_engine="chromium")
        browser_mod = _fresh_import("app.browser", mock_settings)

        with patch.object(browser_mod, "_HAS_PATCHRIGHT", True), \
             patch.object(browser_mod, "async_patchright", return_value=mock_patchright_cm, create=True), \
             patch.object(browser_mod, "settings", mock_settings):
            engine = browser_mod.BrowserEngine()
            await engine.start_browser()

            # Verify patchright was used (not playwright)
            assert engine.playwright is mock_pw

    async def test_chromium_falls_back_to_playwright_when_no_patchright(self):
        """When _HAS_PATCHRIGHT is False, start_browser uses regular playwright."""
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.is_connected.return_value = True
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_pw_start = AsyncMock(return_value=mock_pw)
        mock_pw_cm = MagicMock()
        mock_pw_cm.start = mock_pw_start

        mock_settings = _make_mock_settings(browser_engine="chromium")
        browser_mod = _fresh_import("app.browser", mock_settings)

        with patch.object(browser_mod, "_HAS_PATCHRIGHT", False), \
             patch.object(browser_mod, "async_playwright", return_value=mock_pw_cm), \
             patch.object(browser_mod, "settings", mock_settings):
            engine = browser_mod.BrowserEngine()
            await engine.start_browser()

            assert engine.playwright is mock_pw

    async def test_camoufox_path_unchanged(self):
        """Camoufox path should NOT use patchright -- it uses its own internals."""
        mock_camoufox_browser = AsyncMock()
        mock_camoufox_browser.is_connected.return_value = True
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_camoufox_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_camoufox_browser)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_settings = _make_mock_settings(browser_engine="camoufox")
        browser_mod = _fresh_import("app.browser", mock_settings)

        with patch.object(browser_mod, "settings", mock_settings), \
             patch.dict(sys.modules, {"camoufox.async_api": MagicMock(AsyncCamoufox=MagicMock(return_value=mock_cm))}):
            engine = browser_mod.BrowserEngine()
            await engine.start_browser()

            # Camoufox should NOT touch patchright -- playwright attr is None
            assert engine.playwright is None


@pytest.mark.asyncio
class TestBrowserArgsChromium:
    """Chromium browser args should be hardened for stealth."""

    async def test_disable_web_security_removed(self):
        """--disable-web-security must NOT be in the Chromium browser args."""
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.is_connected.return_value = True
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_pw_start = AsyncMock(return_value=mock_pw)
        mock_pw_cm = MagicMock()
        mock_pw_cm.start = mock_pw_start

        mock_settings = _make_mock_settings(browser_engine="chromium")
        browser_mod = _fresh_import("app.browser", mock_settings)

        with patch.object(browser_mod, "_HAS_PATCHRIGHT", False), \
             patch.object(browser_mod, "async_playwright", return_value=mock_pw_cm), \
             patch.object(browser_mod, "settings", mock_settings):
            engine = browser_mod.BrowserEngine()
            await engine.start_browser()

            launch_call = mock_pw.chromium.launch.call_args
            args_list = launch_call.kwargs.get("args", [])

            assert "--disable-web-security" not in args_list, \
                "--disable-web-security is a detection signal and must be removed"

    async def test_disable_blink_automation_present(self):
        """--disable-blink-features=AutomationControlled must be in args."""
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.is_connected.return_value = True
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_pw_start = AsyncMock(return_value=mock_pw)
        mock_pw_cm = MagicMock()
        mock_pw_cm.start = mock_pw_start

        mock_settings = _make_mock_settings(browser_engine="chromium")
        browser_mod = _fresh_import("app.browser", mock_settings)

        with patch.object(browser_mod, "_HAS_PATCHRIGHT", False), \
             patch.object(browser_mod, "async_playwright", return_value=mock_pw_cm), \
             patch.object(browser_mod, "settings", mock_settings):
            engine = browser_mod.BrowserEngine()
            await engine.start_browser()

            launch_call = mock_pw.chromium.launch.call_args
            args_list = launch_call.kwargs.get("args", [])

            assert "--disable-blink-features=AutomationControlled" in args_list, \
                "Must include --disable-blink-features=AutomationControlled for stealth"


# ---------------------------------------------------------------------------
# browser_pool.py tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestBrowserPoolPatchright:
    """BrowserPool should use patchright for Chromium when available."""

    async def test_pool_start_uses_patchright(self):
        """Pool start() should use async_patchright when _HAS_PATCHRIGHT is True."""
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.is_connected.return_value = True
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False

        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_patchright_start = AsyncMock(return_value=mock_pw)
        mock_patchright_cm = MagicMock()
        mock_patchright_cm.start = mock_patchright_start

        mock_settings = _make_mock_settings()
        pool_mod = _fresh_import("app.browser_pool", mock_settings)

        with patch.object(pool_mod, "_HAS_PATCHRIGHT", True), \
             patch.object(pool_mod, "async_patchright", return_value=mock_patchright_cm, create=True), \
             patch.object(pool_mod, "settings", mock_settings):
            pool = pool_mod.BrowserPool(size=1)
            await pool.start()

            # Verify patchright was used
            assert pool._playwright is mock_pw

            await pool.shutdown()

    async def test_pool_start_falls_back_to_playwright(self):
        """Pool start() should use regular playwright when _HAS_PATCHRIGHT is False."""
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.is_connected.return_value = True
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False

        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_pw_start = AsyncMock(return_value=mock_pw)
        mock_pw_cm = MagicMock()
        mock_pw_cm.start = mock_pw_start

        mock_settings = _make_mock_settings()
        pool_mod = _fresh_import("app.browser_pool", mock_settings)

        with patch.object(pool_mod, "_HAS_PATCHRIGHT", False), \
             patch.object(pool_mod, "async_playwright", return_value=mock_pw_cm), \
             patch.object(pool_mod, "settings", mock_settings):
            pool = pool_mod.BrowserPool(size=1)
            await pool.start()

            assert pool._playwright is mock_pw

            await pool.shutdown()

    async def test_pool_args_include_stealth_flag(self):
        """Pool _create_slot() args should include --disable-blink-features=AutomationControlled."""
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.is_connected.return_value = True
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False

        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_pw_start = AsyncMock(return_value=mock_pw)
        mock_pw_cm = MagicMock()
        mock_pw_cm.start = mock_pw_start

        mock_settings = _make_mock_settings()
        pool_mod = _fresh_import("app.browser_pool", mock_settings)

        with patch.object(pool_mod, "_HAS_PATCHRIGHT", False), \
             patch.object(pool_mod, "async_playwright", return_value=mock_pw_cm), \
             patch.object(pool_mod, "settings", mock_settings):
            pool = pool_mod.BrowserPool(size=1)
            await pool.start()

            launch_call = mock_pw.chromium.launch.call_args
            args_list = launch_call.kwargs.get("args", [])

            assert "--disable-blink-features=AutomationControlled" in args_list

            await pool.shutdown()

    async def test_pool_args_no_disable_web_security(self):
        """Pool _create_slot() args must NOT include --disable-web-security."""
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_browser.is_connected.return_value = True
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False

        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_pw_start = AsyncMock(return_value=mock_pw)
        mock_pw_cm = MagicMock()
        mock_pw_cm.start = mock_pw_start

        mock_settings = _make_mock_settings()
        pool_mod = _fresh_import("app.browser_pool", mock_settings)

        with patch.object(pool_mod, "_HAS_PATCHRIGHT", False), \
             patch.object(pool_mod, "async_playwright", return_value=mock_pw_cm), \
             patch.object(pool_mod, "settings", mock_settings):
            pool = pool_mod.BrowserPool(size=1)
            await pool.start()

            launch_call = mock_pw.chromium.launch.call_args
            args_list = launch_call.kwargs.get("args", [])

            assert "--disable-web-security" not in args_list

            await pool.shutdown()
