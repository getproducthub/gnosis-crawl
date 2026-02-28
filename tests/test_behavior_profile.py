"""Tests for app.behavior_profile — session-level behavioral personality profiles."""

import random
from unittest.mock import AsyncMock, patch

import pytest

from app.behavior_profile import BehaviorProfile


# --- BehaviorProfile.random ---


class TestBehaviorProfileRandom:
    def test_returns_behavior_profile(self):
        profile = BehaviorProfile.random()
        assert isinstance(profile, BehaviorProfile)

    def test_all_fields_populated(self):
        profile = BehaviorProfile.random()
        assert profile.delay_min > 0
        assert profile.delay_max > profile.delay_min
        assert profile.scroll_fraction_min > 0
        assert profile.scroll_fraction_max > profile.scroll_fraction_min
        assert 0 <= profile.scroll_back_chance <= 1
        assert profile.mouse_moves >= 1
        assert profile.mouse_step_min >= 1
        assert profile.mouse_step_max >= profile.mouse_step_min
        assert profile.initial_pause_min > 0
        assert profile.initial_pause_max >= profile.initial_pause_min
        assert profile.inter_page_min > 0
        assert profile.inter_page_max >= profile.inter_page_min

    def test_fast_scanner_has_lower_delays(self):
        with patch("app.behavior_profile.random.choice", return_value="fast_scanner"):
            profile = BehaviorProfile.random()
        assert profile.delay_min <= 300
        assert profile.delay_max <= 1500
        assert profile.scroll_back_chance <= 0.10

    def test_careful_reader_has_higher_delays(self):
        with patch("app.behavior_profile.random.choice", return_value="careful_reader"):
            profile = BehaviorProfile.random()
        assert profile.delay_min >= 800
        assert profile.delay_max >= 4000
        assert profile.scroll_back_chance >= 0.15

    def test_average_is_between_extremes(self):
        with patch("app.behavior_profile.random.choice", return_value="average"):
            profile = BehaviorProfile.random()
        assert 300 < profile.delay_min < 800
        assert 1500 < profile.delay_max < 4000

    def test_fast_scanner_less_mouse_moves(self):
        with patch("app.behavior_profile.random.choice", return_value="fast_scanner"):
            profile = BehaviorProfile.random()
        assert profile.mouse_moves <= 3

    def test_careful_reader_more_mouse_moves(self):
        with patch("app.behavior_profile.random.choice", return_value="careful_reader"):
            profile = BehaviorProfile.random()
        assert profile.mouse_moves >= 4

    def test_styles_produce_distinct_inter_page_delays(self):
        with patch("app.behavior_profile.random.choice", return_value="fast_scanner"):
            fast = BehaviorProfile.random()
        with patch("app.behavior_profile.random.choice", return_value="careful_reader"):
            careful = BehaviorProfile.random()

        assert fast.inter_page_max <= careful.inter_page_min

    def test_random_produces_valid_profile_many_times(self):
        """Smoke test: calling random() 50 times always produces valid profiles."""
        random.seed(42)
        for _ in range(50):
            profile = BehaviorProfile.random()
            assert profile.delay_min < profile.delay_max
            assert profile.scroll_fraction_min < profile.scroll_fraction_max
            assert profile.mouse_step_min <= profile.mouse_step_max


# --- Integration with human_behavior ---


class TestBehaviorProfileHumanBehaviorIntegration:
    def test_human_delay_ms_uses_profile_range(self):
        from app.human_behavior import human_delay_ms

        profile = BehaviorProfile(
            delay_min=100, delay_max=200,
            scroll_fraction_min=0.5, scroll_fraction_max=1.0,
            scroll_back_chance=0.1, mouse_moves=2,
            mouse_step_min=3, mouse_step_max=5,
            initial_pause_min=500, initial_pause_max=1500,
            inter_page_min=2000, inter_page_max=5000,
        )

        random.seed(42)
        for _ in range(50):
            val = human_delay_ms(profile=profile)
            assert 100 <= val <= 200

    def test_human_delay_ms_defaults_without_profile(self):
        from app.human_behavior import human_delay_ms

        random.seed(42)
        val = human_delay_ms()
        assert 500 <= val <= 3000

    @pytest.mark.asyncio
    async def test_inter_request_delay_uses_profile(self):
        from app.human_behavior import inter_request_delay

        profile = BehaviorProfile(
            delay_min=100, delay_max=200,
            scroll_fraction_min=0.5, scroll_fraction_max=1.0,
            scroll_back_chance=0.1, mouse_moves=2,
            mouse_step_min=3, mouse_step_max=5,
            initial_pause_min=500, initial_pause_max=1500,
            inter_page_min=1000, inter_page_max=2000,
        )

        with patch("app.human_behavior.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await inter_request_delay(profile=profile)
            delay_seconds = mock_sleep.call_args[0][0]
            assert 1.0 <= delay_seconds <= 2.0

    @pytest.mark.asyncio
    async def test_simulate_mouse_movement_uses_profile(self):
        from app.human_behavior import simulate_mouse_movement

        profile = BehaviorProfile(
            delay_min=100, delay_max=200,
            scroll_fraction_min=0.5, scroll_fraction_max=1.0,
            scroll_back_chance=0.1, mouse_moves=2,
            mouse_step_min=5, mouse_step_max=10,
            initial_pause_min=500, initial_pause_max=1500,
            inter_page_min=2000, inter_page_max=5000,
        )

        page = AsyncMock()
        page.evaluate = AsyncMock(return_value={"width": 1280, "height": 800})
        page.mouse = AsyncMock()
        page.mouse.move = AsyncMock()

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            await simulate_mouse_movement(page, profile=profile)

        # Should use profile.mouse_moves = 2
        assert page.mouse.move.call_count == 2

        # Steps should be in profile range
        for call in page.mouse.move.call_args_list:
            steps = call[1]["steps"]
            assert 5 <= steps <= 10

    @pytest.mark.asyncio
    async def test_human_scroll_uses_profile(self):
        from app.human_behavior import human_scroll

        profile = BehaviorProfile(
            delay_min=100, delay_max=200,
            scroll_fraction_min=0.8, scroll_fraction_max=1.0,
            scroll_back_chance=0.0,  # no back-scroll
            mouse_moves=2,
            mouse_step_min=3, mouse_step_max=5,
            initial_pause_min=500, initial_pause_max=1500,
            inter_page_min=2000, inter_page_max=5000,
        )

        page = AsyncMock()
        page.evaluate = AsyncMock(return_value={"width": 1280, "height": 800})
        page.mouse = AsyncMock()
        page.mouse.move = AsyncMock()

        with patch("app.human_behavior.human_delay", new_callable=AsyncMock):
            await human_scroll(page, scroll_count=3, profile=profile)

        # With scroll_back_chance=0.0, no back-scrolls should occur
        for call in page.evaluate.call_args_list:
            js_arg = call[0][0]
            if "scrollBy" in js_arg and "-" in js_arg:
                pytest.fail("Back-scroll happened with scroll_back_chance=0.0")
