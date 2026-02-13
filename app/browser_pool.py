"""Persistent Chromium pool for live browser streaming.

Maintains a fixed-size pool of warm Chromium browser instances that can be
leased for streaming sessions. Each slot holds one browser + context + page,
ready to navigate immediately without cold-start latency.

Usage:
    pool = BrowserPool(size=2)
    await pool.start()

    slot = await pool.acquire(session_id="abc123")
    await slot.page.goto("https://example.com")
    # ... stream frames from slot.page ...
    await pool.release(slot)

    await pool.shutdown()
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class PoolSlot:
    """A single browser slot in the pool."""
    slot_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    session_id: Optional[str] = None
    leased: bool = False
    leased_at: float = 0.0
    created_at: float = field(default_factory=time.monotonic)
    navigated_url: Optional[str] = None


class BrowserPool:
    """Fixed-size pool of warm Chromium instances for streaming."""

    def __init__(self, size: int = 1, max_lease_seconds: int = 300):
        self.size = max(1, size)
        self.max_lease_seconds = max_lease_seconds
        self._playwright: Optional[Playwright] = None
        self._slots: list[PoolSlot] = []
        self._lock = asyncio.Lock()
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize the pool with warm browser instances."""
        async with self._lock:
            if self._started:
                return

            logger.info("Starting browser pool (size=%d)", self.size)
            self._playwright = await async_playwright().start()

            for i in range(self.size):
                slot = await self._create_slot()
                self._slots.append(slot)
                logger.info("Pool slot %s ready (%d/%d)", slot.slot_id, i + 1, self.size)

            self._started = True
            logger.info("Browser pool started with %d slots", self.size)

    async def shutdown(self) -> None:
        """Close all browsers and release resources."""
        async with self._lock:
            logger.info("Shutting down browser pool")
            for slot in self._slots:
                await self._destroy_slot(slot)
            self._slots.clear()

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

            self._started = False
            logger.info("Browser pool shut down")

    # ------------------------------------------------------------------
    # Acquire / Release
    # ------------------------------------------------------------------

    async def acquire(self, session_id: str) -> Optional[PoolSlot]:
        """Lease a browser slot for a streaming session.

        Returns None if no slots are available.
        """
        async with self._lock:
            if not self._started:
                await self.start()

            # Reclaim expired leases first
            now = time.monotonic()
            for slot in self._slots:
                if slot.leased and (now - slot.leased_at) > self.max_lease_seconds:
                    logger.warning(
                        "Reclaiming expired slot %s (session=%s, leased %.0fs ago)",
                        slot.slot_id, slot.session_id, now - slot.leased_at,
                    )
                    await self._reset_slot(slot)

            # Find a free slot
            for slot in self._slots:
                if not slot.leased:
                    slot.leased = True
                    slot.leased_at = now
                    slot.session_id = session_id
                    logger.info("Acquired slot %s for session %s", slot.slot_id, session_id)
                    return slot

            logger.warning("No free pool slots (all %d leased)", self.size)
            return None

    async def release(self, slot: PoolSlot) -> None:
        """Return a slot to the pool and reset it for reuse."""
        async with self._lock:
            logger.info("Releasing slot %s (session=%s)", slot.slot_id, slot.session_id)
            await self._reset_slot(slot)

    def get_slot_by_session(self, session_id: str) -> Optional[PoolSlot]:
        """Find the slot currently leased for a session (no lock, read-only)."""
        for slot in self._slots:
            if slot.leased and slot.session_id == session_id:
                return slot
        return None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """Return pool status summary."""
        return {
            "started": self._started,
            "pool_size": self.size,
            "slots": [
                {
                    "slot_id": s.slot_id,
                    "leased": s.leased,
                    "session_id": s.session_id,
                    "url": s.navigated_url,
                    "leased_seconds": int(time.monotonic() - s.leased_at) if s.leased else 0,
                }
                for s in self._slots
            ],
            "free": sum(1 for s in self._slots if not s.leased),
            "leased": sum(1 for s in self._slots if s.leased),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _create_slot(self) -> PoolSlot:
        """Spin up a fresh browser, context, and page."""
        browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--mute-audio",
                "--no-first-run",
                "--headless=new",
            ],
        )

        viewport = {
            "width": settings.browser_stream_max_width,
            "height": int(settings.browser_stream_max_width * 9 / 16),
        }

        context = await browser.new_context(
            viewport=viewport,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.6367.60 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            java_script_enabled=True,
            ignore_https_errors=True,
        )

        page = await context.new_page()

        return PoolSlot(browser=browser, context=context, page=page)

    async def _reset_slot(self, slot: PoolSlot) -> None:
        """Reset a slot for reuse: navigate to blank and clear lease."""
        try:
            if slot.page and not slot.page.is_closed():
                await slot.page.goto("about:blank", timeout=5000)
        except Exception as exc:
            logger.warning("Failed to reset slot %s page: %s", slot.slot_id, exc)
            # Recreate the slot entirely
            await self._destroy_slot(slot)
            new_slot = await self._create_slot()
            slot.browser = new_slot.browser
            slot.context = new_slot.context
            slot.page = new_slot.page
            slot.created_at = new_slot.created_at

        slot.leased = False
        slot.leased_at = 0.0
        slot.session_id = None
        slot.navigated_url = None

    async def _destroy_slot(self, slot: PoolSlot) -> None:
        """Fully close a slot's browser."""
        try:
            if slot.page and not slot.page.is_closed():
                await slot.page.close()
        except Exception:
            pass
        try:
            if slot.context:
                await slot.context.close()
        except Exception:
            pass
        try:
            if slot.browser and slot.browser.is_connected():
                await slot.browser.close()
        except Exception:
            pass
        slot.page = None
        slot.context = None
        slot.browser = None


# ---------------------------------------------------------------------------
# Global pool singleton
# ---------------------------------------------------------------------------

_pool: Optional[BrowserPool] = None


async def get_browser_pool() -> BrowserPool:
    """Get or create the global browser pool."""
    global _pool
    if _pool is None:
        _pool = BrowserPool(
            size=settings.browser_pool_size,
            max_lease_seconds=settings.browser_stream_max_lease_seconds,
        )
    if not _pool._started:
        await _pool.start()
    return _pool


async def shutdown_browser_pool() -> None:
    """Shutdown the global pool (call on app shutdown)."""
    global _pool
    if _pool:
        await _pool.shutdown()
        _pool = None
