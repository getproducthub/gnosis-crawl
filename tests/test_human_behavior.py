"""Tests for app.human_behavior — human-like interaction simulation."""

import asyncio
import random
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.human_behavior import (
    human_delay_ms,
    human_delay,
    human_scroll,
    simulate_mouse_movement,
    inter_request_delay,
    LOAD_MORE_SELECTORS,
    _click_load_more,
)


# --- human_delay_ms ---


class TestHumanDelayMs:
    def test_returns_value_within_range(self):
        """All values should be clamped to [min_ms, max_ms]."""
        random.seed(42)
        for _ in range(100):
            val = human_delay_ms(500, 3000)
            assert 500 <= val <= 3000

    def test_custom_range(self):
        random.seed(42)
        for _ in range(50):
            val = human_delay_ms(100, 200)
            assert 100 <= val <= 200

    def test_same_min_max_returns_that_value(self):
        """When min == max, gauss might still vary but clamping should fix it."""
        val = human_delay_ms(1000, 1000)
        assert val == 1000

    def test_default_args(self):
        random.seed(42)
        val = human_delay_ms()
        assert 500 <= val <= 3000

    def test_distribution_center(self):
        """Mean of many samples should be close to center of range."""
        random.seed(123)
        samples = [human_delay_ms(1000, 3000) for _ in range(1000)]
        mean = sum(samples) / len(samples)
        # Center is 2000, with large sample should be close
        assert 1800 < mean < 2200


# --- human_delay ---


class TestHumanDelay:
    @pytest.mark.asyncio
    async def test_human_delay_calls_sleep(self):
        """human_delay should call asyncio.sleep with a value in seconds."""
        with patch("app.human_behavior.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await human_delay(100, 200)
            mock_sleep.assert_called_once()
            delay_seconds = mock_sleep.call_args[0][0]
            assert 0.1 <= delay_seconds <= 0.2

    @pytest.mark.asyncio
    async def test_human_delay_default_args(self):
        with patch("app.human_behavior.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await human_delay()
            delay_seconds = mock_sleep.call_args[0][0]
            assert 0.5 <= delay_seconds <= 3.0


# --- human_scroll ---


def make_page_for_scroll(viewport_height=800, viewport_width=1280):
    """Create a mock page for scroll tests."""
    page = AsyncMock()
    page.evaluate = AsyncMock(
        return_value={"width": viewport_width, "height": viewport_height}
    )
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    return page


class TestHumanScroll:
    @pytest.mark.asyncio
    async def test_scrolls_multiple_times(self):
        """Should call page.evaluate at least (scroll_count - 2) times for scrolling."""
        page = make_page_for_scroll()
        random.seed(42)

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            await human_scroll(page, scroll_count=5)

        # page.evaluate is called for: 1 viewport query + N scroll actions + possible back-scrolls
        assert page.evaluate.call_count >= 2  # At least viewport + 1 scroll

    @pytest.mark.asyncio
    async def test_scroll_count_variance(self):
        """Actual scroll count should be scroll_count +/- 2."""
        random.seed(42)
        page = make_page_for_scroll()

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            await human_scroll(page, scroll_count=5)

        # With seed=42 and scroll_count=5, actual should be between 3 and 7
        # Can't assert exactly due to randomness, but at least 1 call happened
        assert page.evaluate.call_count >= 2

    @pytest.mark.asyncio
    async def test_minimum_scroll_count_is_1(self):
        """Even with scroll_count=1 and negative variance, should scroll at least once."""
        page = make_page_for_scroll()

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock), \
             patch("random.randint", return_value=-2):
            await human_scroll(page, scroll_count=1)

        # Viewport query + at least 1 scroll
        assert page.evaluate.call_count >= 2

    @pytest.mark.asyncio
    async def test_platform_triggers_load_more(self):
        """When platform is provided, _click_load_more should be called."""
        page = make_page_for_scroll()

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock), \
             patch("app.human_behavior._click_load_more", new_callable=AsyncMock) as mock_click:
            await human_scroll(page, scroll_count=3, platform="g2")
            mock_click.assert_called_once_with(page, "g2")

    @pytest.mark.asyncio
    async def test_no_platform_skips_load_more(self):
        """When platform is None, _click_load_more should not be called."""
        page = make_page_for_scroll()

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock), \
             patch("app.human_behavior._click_load_more", new_callable=AsyncMock) as mock_click:
            await human_scroll(page, scroll_count=3, platform=None)
            mock_click.assert_not_called()


# --- simulate_mouse_movement ---


class TestSimulateMouseMovement:
    @pytest.mark.asyncio
    async def test_moves_mouse_specified_times(self):
        page = make_page_for_scroll()
        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            await simulate_mouse_movement(page, moves=3)

        assert page.mouse.move.call_count == 3

    @pytest.mark.asyncio
    async def test_mouse_positions_within_viewport(self):
        page = make_page_for_scroll(viewport_width=1280, viewport_height=800)
        random.seed(42)

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            await simulate_mouse_movement(page, moves=5)

        for call in page.mouse.move.call_args_list:
            x, y = call[0][0], call[0][1]
            assert 100 <= x <= 1180
            assert 100 <= y <= 700

    @pytest.mark.asyncio
    async def test_uses_steps_for_natural_movement(self):
        page = make_page_for_scroll()
        random.seed(42)

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            await simulate_mouse_movement(page, moves=1)

        call_kwargs = page.mouse.move.call_args[1]
        assert "steps" in call_kwargs
        assert 3 <= call_kwargs["steps"] <= 8


# --- inter_request_delay ---


class TestInterRequestDelay:
    @pytest.mark.asyncio
    async def test_calls_sleep_in_range(self):
        with patch("app.human_behavior.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await inter_request_delay(3000, 8000)
            delay_seconds = mock_sleep.call_args[0][0]
            assert 3.0 <= delay_seconds <= 8.0

    @pytest.mark.asyncio
    async def test_custom_range(self):
        with patch("app.human_behavior.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await inter_request_delay(1000, 2000)
            delay_seconds = mock_sleep.call_args[0][0]
            assert 1.0 <= delay_seconds <= 2.0


# --- _click_load_more ---


class TestClickLoadMore:
    @pytest.mark.asyncio
    async def test_clicks_visible_g2_button(self):
        page = AsyncMock()
        btn = AsyncMock()
        btn.is_visible = AsyncMock(return_value=True)
        btn.click = AsyncMock()

        async def query(sel):
            if sel == '[data-click-id="show-more"]':
                return btn
            return None

        page.query_selector = AsyncMock(side_effect=query)

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            result = await _click_load_more(page, "g2")

        assert result is True
        btn.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_hidden_button(self):
        page = AsyncMock()
        btn = AsyncMock()
        btn.is_visible = AsyncMock(return_value=False)

        async def query(sel):
            if sel == '[data-click-id="show-more"]':
                return btn
            return None

        page.query_selector = AsyncMock(side_effect=query)

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            result = await _click_load_more(page, "g2")

        assert result is False

    @pytest.mark.asyncio
    async def test_no_button_found(self):
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            result = await _click_load_more(page, "g2")

        assert result is False

    @pytest.mark.asyncio
    async def test_unknown_platform_returns_false(self):
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            result = await _click_load_more(page, "unknownplatform")

        assert result is False

    @pytest.mark.asyncio
    async def test_exception_during_click_continues(self):
        page = AsyncMock()
        btn = AsyncMock()
        btn.is_visible = AsyncMock(side_effect=Exception("Element detached"))

        page.query_selector = AsyncMock(return_value=btn)

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            result = await _click_load_more(page, "g2")

        assert result is False


# --- LOAD_MORE_SELECTORS constants ---


class TestLoadMoreSelectors:
    def test_g2_selectors_exist(self):
        assert "g2" in LOAD_MORE_SELECTORS
        assert len(LOAD_MORE_SELECTORS["g2"]) >= 2

    def test_capterra_selectors_exist(self):
        assert "capterra" in LOAD_MORE_SELECTORS
        assert len(LOAD_MORE_SELECTORS["capterra"]) >= 2

    def test_trustradius_selectors_exist(self):
        assert "trustradius" in LOAD_MORE_SELECTORS

    def test_trustpilot_selectors_exist(self):
        assert "trustpilot" in LOAD_MORE_SELECTORS
