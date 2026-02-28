"""Warm-up navigation: Google search -> click -> target URL.

Navigates to Google, searches for the target, and clicks through if a
matching link is found. This establishes a natural referrer chain and
picks up Google cookies, making subsequent navigation to review sites
appear more organic to Cloudflare bot detection.
"""

import asyncio
import logging
import random
import re
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)

# Platform domains for warm-up queries
PLATFORM_DOMAINS = {
    "trustpilot": "trustpilot.com",
    "g2": "g2.com",
    "capterra": "capterra.com",
    "trustradius": "trustradius.com",
}


def build_warmup_query(competitor_name: str, platform: str) -> str:
    """Build a natural-looking search query for warm-up navigation."""
    domain = PLATFORM_DOMAINS.get(platform, "")
    if domain:
        return f'"{competitor_name}" reviews site:{domain}'
    return f'"{competitor_name}" reviews'


async def warmup_via_google(
    page,
    target_url: str,
    search_query: str,
    timeout_ms: int = 12000,
) -> bool:
    """Navigate to Google, search for target, click through if found.

    Returns True if warm-up succeeded (clicked through), False if
    skipped/failed. Falls back gracefully -- caller should proceed
    with direct navigation on failure.
    """
    try:
        encoded_query = urllib.parse.quote(search_query)
        google_url = f"https://www.google.com/search?q={encoded_query}"

        await page.goto(google_url, timeout=timeout_ms, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(1.0, 2.5))

        # Extract domain from target URL for matching
        domain_match = re.search(r"//([^/]+)", target_url)
        if not domain_match:
            return False
        domain = domain_match.group(1).replace("www.", "")

        links = await page.query_selector_all(f'a[href*="{domain}"]')

        if links:
            await links[0].click()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass  # Page may have already loaded
            return True

        return False
    except Exception as e:
        logger.debug(f"Warm-up navigation failed: {e}")
        return False
