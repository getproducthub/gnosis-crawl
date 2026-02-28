"""Tests for WS2: Chromium launch args expansion + JS stealth patches.

Validates:
- CHROMIUM_STEALTH_ARGS constant exists and has >= 30 entries
- Critical stealth flags are present
- --disable-web-security is NOT in CHROMIUM_STEALTH_ARGS
- JS patches are called for Chromium pages
- JS patches are skipped for Camoufox pages
- browser_pool uses CHROMIUM_STEALTH_ARGS
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
    s.stealth_enabled = overrides.get("stealth_enabled", True)
    s.block_tracking_domains = overrides.get("block_tracking_domains", False)
    s.get_proxy_config.return_value = None
    return s


def _fresh_import(module_name, mock_settings):
    """Force a fresh import of a module with mocked settings."""
    for key in list(sys.modules.keys()):
        if key == module_name or key == "app.config":
            del sys.modules[key]
    fake_config = MagicMock()
    fake_config.settings = mock_settings
    sys.modules["app.config"] = fake_config
    return importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# Part A: CHROMIUM_STEALTH_ARGS constant
# ---------------------------------------------------------------------------

class TestChromiumStealthArgsConstant:
    """CHROMIUM_STEALTH_ARGS should be a well-populated constant."""

    def test_constant_exists(self):
        """CHROMIUM_STEALTH_ARGS must be defined at module level."""
        mock_settings = _make_mock_settings()
        browser_mod = _fresh_import("app.browser", mock_settings)
        assert hasattr(browser_mod, "CHROMIUM_STEALTH_ARGS"), \
            "app.browser must export CHROMIUM_STEALTH_ARGS constant"

    def test_minimum_30_entries(self):
        """Constant must have at least 30 args for comprehensive stealth."""
        mock_settings = _make_mock_settings()
        browser_mod = _fresh_import("app.browser", mock_settings)
        args = browser_mod.CHROMIUM_STEALTH_ARGS
        assert len(args) >= 30, \
            f"Expected >= 30 stealth args, got {len(args)}"

    def test_no_disable_web_security(self):
        """--disable-web-security must NOT be in the args (detection signal)."""
        mock_settings = _make_mock_settings()
        browser_mod = _fresh_import("app.browser", mock_settings)
        args = browser_mod.CHROMIUM_STEALTH_ARGS
        assert "--disable-web-security" not in args

    def test_automation_controlled_present(self):
        """--disable-blink-features=AutomationControlled must be present."""
        mock_settings = _make_mock_settings()
        browser_mod = _fresh_import("app.browser", mock_settings)
        args = browser_mod.CHROMIUM_STEALTH_ARGS
        assert "--disable-blink-features=AutomationControlled" in args

    def test_webrtc_leak_protection_present(self):
        """WebRTC IP handling policy arg must be present."""
        mock_settings = _make_mock_settings()
        browser_mod = _fresh_import("app.browser", mock_settings)
        args = browser_mod.CHROMIUM_STEALTH_ARGS
        assert "--webrtc-ip-handling-policy=disable_non_proxied_udp" in args

    def test_canvas_noise_present(self):
        """Canvas fingerprint noise arg must be present."""
        mock_settings = _make_mock_settings()
        browser_mod = _fresh_import("app.browser", mock_settings)
        args = browser_mod.CHROMIUM_STEALTH_ARGS
        assert "--fingerprinting-canvas-image-data-noise" in args

    def test_color_profile_present(self):
        """Consistent color profile rendering arg must be present."""
        mock_settings = _make_mock_settings()
        browser_mod = _fresh_import("app.browser", mock_settings)
        args = browser_mod.CHROMIUM_STEALTH_ARGS
        assert "--force-color-profile=srgb" in args

    def test_breakpad_disabled(self):
        """Crash reporting must be disabled (detection signal)."""
        mock_settings = _make_mock_settings()
        browser_mod = _fresh_import("app.browser", mock_settings)
        args = browser_mod.CHROMIUM_STEALTH_ARGS
        assert "--disable-breakpad" in args


class TestBrowserEngineUsesStealthArgs:
    """BrowserEngine.start_browser() should use CHROMIUM_STEALTH_ARGS."""

    @pytest.mark.asyncio
    async def test_start_browser_uses_constant(self):
        """Launch args should come from CHROMIUM_STEALTH_ARGS."""
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

            # Should contain all args from constant (headless extras may be appended)
            stealth_args = browser_mod.CHROMIUM_STEALTH_ARGS
            for arg in stealth_args:
                assert arg in args_list, f"Missing stealth arg: {arg}"


class TestBrowserPoolUsesStealthArgs:
    """BrowserPool._create_slot() should use CHROMIUM_STEALTH_ARGS."""

    @pytest.mark.asyncio
    async def test_pool_uses_stealth_constant(self):
        """Pool launch args should include CHROMIUM_STEALTH_ARGS entries."""
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
        browser_mod = _fresh_import("app.browser", mock_settings)

        with patch.object(pool_mod, "_HAS_PATCHRIGHT", False), \
             patch.object(pool_mod, "async_playwright", return_value=mock_pw_cm), \
             patch.object(pool_mod, "settings", mock_settings):
            pool = pool_mod.BrowserPool(size=1)
            await pool.start()

            launch_call = mock_pw.chromium.launch.call_args
            args_list = launch_call.kwargs.get("args", [])

            # Must include key stealth args
            assert "--disable-blink-features=AutomationControlled" in args_list
            assert "--webrtc-ip-handling-policy=disable_non_proxied_udp" in args_list
            assert "--disable-web-security" not in args_list

            await pool.shutdown()


# ---------------------------------------------------------------------------
# Part B: JS stealth patches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestApplyChromiumJsPatches:
    """apply_chromium_js_patches(page) function tests."""

    async def test_function_exists(self):
        """apply_chromium_js_patches must be importable from app.stealth."""
        mock_settings = _make_mock_settings()
        stealth_mod = _fresh_import("app.stealth", mock_settings)
        assert hasattr(stealth_mod, "apply_chromium_js_patches"), \
            "app.stealth must export apply_chromium_js_patches"

    async def test_calls_add_init_script_for_chromium(self):
        """JS patches should call page.add_init_script for chromium engine."""
        mock_page = AsyncMock()
        mock_settings = _make_mock_settings(browser_engine="chromium")
        stealth_mod = _fresh_import("app.stealth", mock_settings)

        with patch.object(stealth_mod, "settings", mock_settings):
            await stealth_mod.apply_chromium_js_patches(mock_page)
            mock_page.add_init_script.assert_called_once()

    async def test_skips_for_camoufox(self):
        """JS patches should be skipped for Camoufox engine."""
        mock_page = AsyncMock()
        mock_settings = _make_mock_settings(browser_engine="camoufox")
        stealth_mod = _fresh_import("app.stealth", mock_settings)

        with patch.object(stealth_mod, "settings", mock_settings):
            await stealth_mod.apply_chromium_js_patches(mock_page)
            mock_page.add_init_script.assert_not_called()

    async def test_patches_contain_notification_fix(self):
        """JS patches should fix Notification.permission detection."""
        mock_page = AsyncMock()
        mock_settings = _make_mock_settings(browser_engine="chromium")
        stealth_mod = _fresh_import("app.stealth", mock_settings)

        with patch.object(stealth_mod, "settings", mock_settings):
            await stealth_mod.apply_chromium_js_patches(mock_page)
            js_code = mock_page.add_init_script.call_args[0][0]
            assert "Notification" in js_code

    async def test_patches_remove_playwright_globals(self):
        """JS patches should remove __playwright globals."""
        mock_page = AsyncMock()
        mock_settings = _make_mock_settings(browser_engine="chromium")
        stealth_mod = _fresh_import("app.stealth", mock_settings)

        with patch.object(stealth_mod, "settings", mock_settings):
            await stealth_mod.apply_chromium_js_patches(mock_page)
            js_code = mock_page.add_init_script.call_args[0][0]
            assert "__playwright" in js_code


@pytest.mark.asyncio
class TestJsPatchesIntegration:
    """JS patches should be called during browser startup and context creation."""

    async def test_start_browser_calls_js_patches(self):
        """start_browser() should call apply_chromium_js_patches on the new page."""
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

        mock_apply_patches = AsyncMock()

        with patch.object(browser_mod, "_HAS_PATCHRIGHT", False), \
             patch.object(browser_mod, "async_playwright", return_value=mock_pw_cm), \
             patch.object(browser_mod, "settings", mock_settings), \
             patch("app.browser.apply_chromium_js_patches", mock_apply_patches, create=True):
            engine = browser_mod.BrowserEngine()
            await engine.start_browser()

            mock_apply_patches.assert_called_once_with(mock_page)

    async def test_create_isolated_context_calls_js_patches(self):
        """create_isolated_context() should call apply_chromium_js_patches on the page."""
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

        mock_apply_stealth = AsyncMock()
        mock_setup_interception = AsyncMock()
        mock_apply_patches = AsyncMock()

        with patch.object(browser_mod, "_HAS_PATCHRIGHT", False), \
             patch.object(browser_mod, "async_playwright", return_value=mock_pw_cm), \
             patch.object(browser_mod, "settings", mock_settings), \
             patch("app.stealth.apply_stealth", mock_apply_stealth), \
             patch("app.stealth.setup_request_interception", mock_setup_interception), \
             patch("app.stealth.apply_chromium_js_patches", mock_apply_patches, create=True):
            engine = browser_mod.BrowserEngine()
            # Start browser first
            await engine.start_browser()

            # Now create isolated context
            stealth_mod = _fresh_import("app.stealth", mock_settings)
            with patch.object(stealth_mod, "apply_chromium_js_patches", mock_apply_patches):
                ctx, page = await engine.create_isolated_context()
                # apply_chromium_js_patches should have been called for the new page
                mock_apply_patches.assert_called()
