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


async def setup_request_interception(context) -> None:
    """Register request interception to block tracking/analytics domains."""
    if not settings.block_tracking_domains:
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
