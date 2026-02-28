"""Stealth module: playwright-stealth patches, request interception, proxy resolution."""

import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Domains to block (analytics, tracking, anti-bot telemetry)
BLOCKED_DOMAINS = [
    "google-analytics.com",
    "googletagmanager.com",
    "facebook.net",
    "connect.facebook.net",
    "doubleclick.net",
    "hotjar.com",
    "clarity.ms",
    "perimeterx.net",
    "datadome.co",
    "imperva.com",
    "kasada.io",
    "queue-it.net",
    "sentry.io",
    "bugsnag.com",
    "segment.io",
    "mixpanel.com",
    "amplitude.com",
    "intercom.io",
    "drift.com",
]


async def apply_stealth(context) -> None:
    """Apply playwright-stealth patches to a browser context."""
    if not settings.stealth_enabled:
        return
    if settings.browser_engine == "camoufox":
        logger.debug("Camoufox engine: stealth is built-in, skipping playwright-stealth")
        return
    try:
        from playwright_stealth import Stealth
        stealth = Stealth()
        await stealth.apply_stealth_async(context)
        logger.debug("Applied playwright-stealth patches")
    except ImportError:
        logger.warning("playwright-stealth not installed, skipping stealth patches")
    except Exception as exc:
        logger.warning("Failed to apply stealth patches: %s", exc)


_CHROMIUM_JS_PATCHES = """
// Fix Notification.permission (headless returns 'denied', a detection signal)
try {
    Object.defineProperty(Notification, 'permission', {
        get: () => 'default',
        configurable: true
    });
} catch(e) {}

// Remove Playwright global markers
const pwGlobals = Object.getOwnPropertyNames(window).filter(
    k => k.startsWith('__playwright') || k === '__pwInitScripts'
);
for (const key of pwGlobals) {
    try { delete window[key]; } catch(e) {}
}

// WebGL renderer spoofing (hide SwiftShader/headless indicators)
try {
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Google Inc. (Intel)';
        if (param === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630, OpenGL 4.1)';
        return getParam.call(this, param);
    };
} catch(e) {}

// AudioContext fingerprint noise
try {
    const origGetFloatFreqData = AnalyserNode.prototype.getFloatFrequencyData;
    AnalyserNode.prototype.getFloatFrequencyData = function(array) {
        origGetFloatFreqData.call(this, array);
        for (let i = 0; i < array.length; i++) {
            array[i] += (Math.random() - 0.5) * 0.001;
        }
    };
} catch(e) {}
"""


async def apply_chromium_js_patches(page) -> None:
    """Inject JS patches to hide Chromium/Playwright detection signals.

    Skipped for Camoufox which handles stealth at C++ level.
    """
    if settings.browser_engine == "camoufox":
        return
    try:
        await page.add_init_script(_CHROMIUM_JS_PATCHES)
        logger.debug("Applied Chromium JS stealth patches")
    except Exception as exc:
        logger.warning("Failed to apply JS stealth patches: %s", exc)


async def setup_request_interception(context) -> None:
    """Register request interception to block tracking/analytics domains.

    For Camoufox (Firefox-based) with proxy: uses per-domain route patterns
    that only call ``route.abort()``.  A catch-all ``context.route("**/*", ...)``
    would require ``route.continue_()`` for non-blocked requests, which fails
    on Firefox to re-route through the proxy.  Domain-specific routes avoid
    this — unmatched requests flow through the proxy normally.
    """
    if not settings.block_tracking_domains:
        return

    if settings.browser_engine == "camoufox":
        # Per-domain routes: only abort(), never continue_()
        for domain in BLOCKED_DOMAINS:
            await context.route(
                f"**/*{domain}*",
                lambda route: route.abort(),
            )
        logger.debug("Camoufox: blocking %d tracking domains via per-domain routes", len(BLOCKED_DOMAINS))
        return

    async def _route_handler(route):
        url = route.request.url.lower()
        for domain in BLOCKED_DOMAINS:
            if domain in url:
                logger.debug("Blocked request to %s", domain)
                await route.abort()
                return
        await route.continue_()

    await context.route("**/*", _route_handler)
    logger.debug("Request interception enabled (%d blocked domains)", len(BLOCKED_DOMAINS))


def resolve_proxy(request_proxy=None, app_settings=None) -> Optional[dict]:
    """Merge per-request proxy with env-based default. Request takes priority."""
    s = app_settings or settings

    # Per-request proxy takes priority
    if request_proxy is not None:
        if hasattr(request_proxy, 'model_dump'):
            proxy_dict = request_proxy.model_dump(exclude_none=True)
        elif isinstance(request_proxy, dict):
            proxy_dict = {k: v for k, v in request_proxy.items() if v is not None}
        else:
            proxy_dict = None
        if proxy_dict and proxy_dict.get("server"):
            return proxy_dict

    # Fall back to env-based default
    return s.get_proxy_config()
