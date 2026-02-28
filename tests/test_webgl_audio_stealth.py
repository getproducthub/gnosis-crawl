"""Tests for WebGL/Audio fingerprint patches in stealth.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestChromiumJsPatchesWebGL:
    """_CHROMIUM_JS_PATCHES should include WebGL renderer spoofing."""

    def test_contains_webgl_param_37445(self):
        """WebGL UNMASKED_VENDOR_WEBGL (37445) override should be present."""
        from app.stealth import _CHROMIUM_JS_PATCHES
        assert "37445" in _CHROMIUM_JS_PATCHES

    def test_contains_webgl_param_37446(self):
        """WebGL UNMASKED_RENDERER_WEBGL (37446) override should be present."""
        from app.stealth import _CHROMIUM_JS_PATCHES
        assert "37446" in _CHROMIUM_JS_PATCHES

    def test_webgl_returns_intel_vendor(self):
        """WebGL vendor spoof should return Intel identifier."""
        from app.stealth import _CHROMIUM_JS_PATCHES
        assert "Google Inc. (Intel)" in _CHROMIUM_JS_PATCHES

    def test_webgl_returns_intel_renderer(self):
        """WebGL renderer spoof should return Intel UHD Graphics identifier."""
        from app.stealth import _CHROMIUM_JS_PATCHES
        assert "ANGLE (Intel" in _CHROMIUM_JS_PATCHES

    def test_patches_webglrenderingcontext(self):
        """Should override WebGLRenderingContext.prototype.getParameter."""
        from app.stealth import _CHROMIUM_JS_PATCHES
        assert "WebGLRenderingContext.prototype.getParameter" in _CHROMIUM_JS_PATCHES


class TestChromiumJsPatchesAudio:
    """_CHROMIUM_JS_PATCHES should include AudioContext fingerprint noise."""

    def test_contains_analyser_node_override(self):
        """Should override AnalyserNode.prototype.getFloatFrequencyData."""
        from app.stealth import _CHROMIUM_JS_PATCHES
        assert "AnalyserNode.prototype.getFloatFrequencyData" in _CHROMIUM_JS_PATCHES

    def test_contains_noise_injection(self):
        """Should inject randomized noise into audio data."""
        from app.stealth import _CHROMIUM_JS_PATCHES
        assert "Math.random()" in _CHROMIUM_JS_PATCHES

    def test_noise_magnitude_is_small(self):
        """Noise should be small (0.001) to avoid audible artifacts."""
        from app.stealth import _CHROMIUM_JS_PATCHES
        assert "0.001" in _CHROMIUM_JS_PATCHES


@pytest.mark.asyncio
class TestApplyChromiumJsPatches:
    """apply_chromium_js_patches() should skip for Camoufox."""

    async def test_skipped_for_camoufox_engine(self):
        """Patches should NOT be applied when engine is camoufox."""
        mock_page = AsyncMock()

        with patch("app.stealth.settings") as mock_settings:
            mock_settings.browser_engine = "camoufox"

            from app.stealth import apply_chromium_js_patches
            await apply_chromium_js_patches(mock_page)

            mock_page.add_init_script.assert_not_called()

    async def test_applied_for_chromium_engine(self):
        """Patches SHOULD be applied when engine is chromium."""
        mock_page = AsyncMock()

        with patch("app.stealth.settings") as mock_settings:
            mock_settings.browser_engine = "chromium"

            from app.stealth import apply_chromium_js_patches
            await apply_chromium_js_patches(mock_page)

            mock_page.add_init_script.assert_called_once()
            script = mock_page.add_init_script.call_args[0][0]
            assert "37445" in script
            assert "AnalyserNode" in script
