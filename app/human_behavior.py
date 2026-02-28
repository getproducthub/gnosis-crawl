"""
Human-Like Behavior Simulation for gnosis-crawl.

Generates realistic human interaction patterns (scrolling, mouse movement,
delays) to reduce bot detection risk on review sites.
"""

import asyncio
import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)


def human_delay_ms(min_ms: int = 500, max_ms: int = 3000, profile=None) -> float:
    """
    Generate a human-like delay in milliseconds using normal distribution.

    Center of distribution is at (min + max) / 2, with sigma covering
    the range. Values are clamped to [min, max].

    Args:
        min_ms: Minimum delay (overridden by profile.delay_min if profile given)
        max_ms: Maximum delay (overridden by profile.delay_max if profile given)
        profile: Optional BehaviorProfile to source ranges from

    Returns:
        Delay in milliseconds
    """
    if profile is not None:
        min_ms = profile.delay_min
        max_ms = profile.delay_max
    center = (min_ms + max_ms) / 2
    sigma = (max_ms - min_ms) / 4  # ~95% within range
    delay = random.gauss(center, sigma)
    return max(min_ms, min(max_ms, delay))


async def human_delay(min_ms: int = 500, max_ms: int = 3000):
    """Sleep for a human-like duration."""
    delay_ms = human_delay_ms(min_ms, max_ms)
    await asyncio.sleep(delay_ms / 1000)


async def human_scroll(page, scroll_count: int = 5, platform: Optional[str] = None, profile=None):
    """
    Scroll the page like a human: variable speed, pauses, slight randomization.

    Args:
        page: Playwright page object
        scroll_count: Approximate number of scroll actions (+-2 variance)
        platform: Optional platform hint for scroll behavior
        profile: Optional BehaviorProfile for scroll parameters
    """
    # Randomize actual scroll count
    actual_count = max(1, scroll_count + random.randint(-2, 2))

    viewport = await page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
    viewport_height = viewport.get("height", 800)

    scroll_frac_min = profile.scroll_fraction_min if profile else 0.6
    scroll_frac_max = profile.scroll_fraction_max if profile else 1.2
    scroll_back_chance = profile.scroll_back_chance if profile else 0.1

    for i in range(actual_count):
        # Variable scroll distance
        scroll_fraction = random.uniform(scroll_frac_min, scroll_frac_max)
        scroll_px = int(viewport_height * scroll_fraction)

        await page.evaluate(f"""() => {{
            window.scrollBy({{
                top: {scroll_px},
                behavior: 'smooth'
            }});
        }}""")

        # Random pause between scrolls (longer for first few, shorter later)
        if i < 2:
            await human_delay(1000, 3000)
        else:
            await human_delay(400, 1500)

        # Occasionally scroll back up a bit
        if random.random() < scroll_back_chance and i > 0:
            back_px = random.randint(50, 200)
            await page.evaluate(f"() => window.scrollBy({{ top: -{back_px}, behavior: 'smooth' }})")
            await human_delay(200, 600)

    # Platform-specific "load more" clicks
    if platform:
        await _click_load_more(page, platform)


async def simulate_mouse_movement(page, moves: int = 3, profile=None):
    """
    Move the mouse to random positions to trigger hover events.

    Args:
        page: Playwright page object
        moves: Number of random mouse movements (overridden by profile.mouse_moves)
        profile: Optional BehaviorProfile for movement parameters
    """
    if profile is not None:
        moves = profile.mouse_moves

    viewport = await page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
    width = viewport.get("width", 1280)
    height = viewport.get("height", 800)

    step_min = profile.mouse_step_min if profile else 3
    step_max = profile.mouse_step_max if profile else 8

    for _ in range(moves):
        x = random.randint(100, width - 100)
        y = random.randint(100, height - 100)

        # Move with steps for more natural path
        steps = random.randint(step_min, step_max)
        await page.mouse.move(x, y, steps=steps)
        await human_delay(100, 500)


async def inter_request_delay(min_ms: int = 3000, max_ms: int = 8000, profile=None):
    """
    Longer delay between full page loads.
    Simulates human reading/thinking time between pages.

    Args:
        min_ms: Minimum delay (overridden by profile.inter_page_min)
        max_ms: Maximum delay (overridden by profile.inter_page_max)
        profile: Optional BehaviorProfile for delay parameters
    """
    if profile is not None:
        min_ms = profile.inter_page_min
        max_ms = profile.inter_page_max
    delay_ms = human_delay_ms(min_ms, max_ms)
    logger.debug(f"Inter-request delay: {delay_ms:.0f}ms")
    await asyncio.sleep(delay_ms / 1000)


# --- Platform-specific helpers ---

LOAD_MORE_SELECTORS = {
    "g2": ['[data-click-id="show-more"]', '.show-more-link', 'button[class*="show-more"]'],
    "capterra": ['.ct-load-more', '.load-more-btn', 'button[data-testid="load-more"]'],
    "trustradius": ['button[class*="load-more"]', '.load-more-reviews'],
    "trustpilot": ['button[name="show-more-reviews"]', '.styles_paginationButtonNext'],
}


async def _click_load_more(page, platform: str):
    """Try clicking platform-specific 'load more' buttons."""
    selectors = LOAD_MORE_SELECTORS.get(platform, [])

    for selector in selectors:
        try:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                await human_delay(500, 1500)  # Pause before clicking
                await btn.click()
                await human_delay(1500, 3000)  # Wait for content to load
                logger.debug(f"Clicked load-more: {selector}")
                return True
        except Exception:
            continue

    return False
