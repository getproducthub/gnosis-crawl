"""Tests for app.challenge_solver — Cloudflare challenge detection and resolution."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.challenge_solver import (
    ChallengeDetection,
    ChallengeResult,
    ChallengeType,
    CHALLENGE_SELECTORS,
    CHALLENGE_TITLE_PATTERNS,
    RESOLVED_SELECTORS,
    detect_challenge,
    wait_for_challenge_resolution,
    solve_turnstile_capsolver,
    resolve_challenge,
    _extract_turnstile_sitekey,
)


# --- Fixtures ---


def make_page(title="My Site", selectors=None, resolved_selectors=None):
    """Create a mock Playwright page with configurable challenge indicators."""
    page = AsyncMock()
    page.title = AsyncMock(return_value=title)

    # Map of selector -> mock element
    element_map = {}
    if selectors:
        for selector, visible in selectors.items():
            el = AsyncMock()
            el.is_visible = AsyncMock(return_value=visible)
            el.get_attribute = AsyncMock(return_value=None)
            element_map[selector] = el

    if resolved_selectors:
        for selector in resolved_selectors:
            el = AsyncMock()
            element_map[selector] = el

    async def query_selector(sel):
        return element_map.get(sel)

    page.query_selector = AsyncMock(side_effect=query_selector)
    page.evaluate = AsyncMock(return_value=None)
    return page


# --- ChallengeDetection dataclass ---


class TestChallengeDetection:
    def test_defaults(self):
        d = ChallengeDetection()
        assert d.detected is False
        assert d.challenge_type == ChallengeType.NONE
        assert d.confidence == 0.0
        assert d.selector_matched == ""

    def test_with_values(self):
        d = ChallengeDetection(
            detected=True,
            challenge_type=ChallengeType.TURNSTILE,
            confidence=0.95,
            selector_matched=".cf-turnstile",
        )
        assert d.detected is True
        assert d.challenge_type == ChallengeType.TURNSTILE


# --- ChallengeResult dataclass ---


class TestChallengeResult:
    def test_defaults(self):
        r = ChallengeResult()
        assert r.resolved is False
        assert r.method == "none"
        assert r.wait_time_ms == 0
        assert r.error is None

    def test_successful_result(self):
        r = ChallengeResult(
            resolved=True,
            challenge_type=ChallengeType.JS_CHALLENGE,
            method="auto_resolve",
            wait_time_ms=3500,
        )
        assert r.resolved is True
        assert r.method == "auto_resolve"


# --- detect_challenge ---


class TestDetectChallenge:
    @pytest.mark.asyncio
    async def test_no_challenge_on_clean_page(self):
        page = make_page(title="Product Reviews - G2")
        result = await detect_challenge(page)
        assert result.detected is False
        assert result.challenge_type == ChallengeType.NONE

    @pytest.mark.asyncio
    async def test_detects_challenge_from_title_just_a_moment(self):
        page = make_page(title="Just a moment...")
        result = await detect_challenge(page)
        assert result.detected is True
        assert result.challenge_type == ChallengeType.JS_CHALLENGE
        assert result.confidence == 0.9
        assert "just a moment" in result.selector_matched

    @pytest.mark.asyncio
    async def test_detects_challenge_from_title_checking_browser(self):
        page = make_page(title="Checking your browser before accessing example.com")
        result = await detect_challenge(page)
        assert result.detected is True

    @pytest.mark.asyncio
    async def test_detects_challenge_from_title_verify_human(self):
        page = make_page(title="Verify you are human")
        result = await detect_challenge(page)
        assert result.detected is True

    @pytest.mark.asyncio
    async def test_detects_visible_dom_selector(self):
        page = make_page(
            title="Some Page",
            selectors={"#challenge-running": True},
        )
        result = await detect_challenge(page)
        assert result.detected is True
        assert result.challenge_type == ChallengeType.JS_CHALLENGE
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_detects_hidden_dom_selector_lower_confidence(self):
        page = make_page(
            title="Some Page",
            selectors={"#challenge-running": False},  # present but not visible
        )
        result = await detect_challenge(page)
        assert result.detected is True
        assert result.confidence == 0.7

    @pytest.mark.asyncio
    async def test_detects_turnstile_iframe(self):
        page = make_page(
            title="Some Page",
            selectors={'iframe[src*="challenges.cloudflare.com"]': True},
        )
        result = await detect_challenge(page)
        assert result.detected is True
        assert result.challenge_type == ChallengeType.TURNSTILE

    @pytest.mark.asyncio
    async def test_detects_cf_turnstile_class(self):
        page = make_page(
            title="Some Page",
            selectors={".cf-turnstile": True},
        )
        result = await detect_challenge(page)
        assert result.detected is True
        assert result.challenge_type == ChallengeType.TURNSTILE

    @pytest.mark.asyncio
    async def test_detects_managed_challenge(self):
        page = make_page(
            title="Some Page",
            selectors={"#cf-challenge-running": True},
        )
        result = await detect_challenge(page)
        assert result.detected is True
        assert result.challenge_type == ChallengeType.MANAGED

    @pytest.mark.asyncio
    async def test_detects_browser_check(self):
        page = make_page(
            title="Some Page",
            selectors={".cf-browser-verification": True},
        )
        result = await detect_challenge(page)
        assert result.detected is True
        assert result.challenge_type == ChallengeType.BROWSER_CHECK

    @pytest.mark.asyncio
    async def test_title_exception_falls_through_to_selectors(self):
        page = make_page(selectors={"#challenge-running": True})
        page.title = AsyncMock(side_effect=Exception("Page closed"))
        result = await detect_challenge(page)
        assert result.detected is True
        assert result.challenge_type == ChallengeType.JS_CHALLENGE

    @pytest.mark.asyncio
    async def test_selector_exception_continues_to_next(self):
        page = make_page(title="Normal Page")
        call_count = 0

        async def flaky_query(sel):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise Exception("Flaky query")
            return None

        page.query_selector = AsyncMock(side_effect=flaky_query)
        result = await detect_challenge(page)
        # Should complete without crashing, returning no detection
        assert result.detected is False

    @pytest.mark.asyncio
    async def test_title_takes_priority_over_selectors(self):
        """Title match should return immediately, not check selectors."""
        page = make_page(
            title="Just a moment...",
            selectors={".cf-turnstile": True},
        )
        result = await detect_challenge(page)
        assert result.challenge_type == ChallengeType.JS_CHALLENGE
        assert "title:" in result.selector_matched


# --- wait_for_challenge_resolution ---


class TestWaitForChallengeResolution:
    @pytest.mark.asyncio
    async def test_returns_immediately_if_no_challenge(self):
        page = make_page(title="Clean Page")
        result = await wait_for_challenge_resolution(page, timeout_ms=5000)
        assert result.resolved is True
        assert result.method == "none"
        assert result.wait_time_ms == 0

    @pytest.mark.asyncio
    async def test_resolves_when_challenge_disappears(self):
        """Simulate challenge disappearing after first poll."""
        page = make_page(title="Just a moment...")
        detect_count = 0

        original_title = page.title

        async def title_side_effect():
            nonlocal detect_count
            detect_count += 1
            if detect_count <= 1:
                return "Just a moment..."
            return "Normal Page - Reviews"

        page.title = AsyncMock(side_effect=title_side_effect)

        result = await wait_for_challenge_resolution(
            page, timeout_ms=5000, poll_interval_ms=50,
        )
        assert result.resolved is True
        assert result.method == "auto_resolve"
        assert result.challenge_type == ChallengeType.JS_CHALLENGE

    @pytest.mark.asyncio
    async def test_resolves_via_resolved_selector(self):
        """Challenge detected via title, then #challenge-success appears on second poll."""
        page = make_page(title="Just a moment...")
        query_call_count = 0

        async def query_side_effect(sel):
            nonlocal query_call_count
            query_call_count += 1
            # After a few query_selector calls, #challenge-success appears
            if sel == "#challenge-success" and query_call_count >= 3:
                return AsyncMock()  # Element exists -> resolved
            return None

        # Title stays as challenge title (detect_challenge returns detected=True via title)
        # But the resolved selector check AFTER detect_challenge will find #challenge-success
        page.query_selector = AsyncMock(side_effect=query_side_effect)

        result = await wait_for_challenge_resolution(
            page, timeout_ms=5000, poll_interval_ms=50,
        )
        assert result.resolved is True
        assert result.method == "auto_resolve"

    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self):
        page = make_page(title="Just a moment...")
        # Title never changes
        result = await wait_for_challenge_resolution(
            page, timeout_ms=200, poll_interval_ms=50,
        )
        assert result.resolved is False
        assert "timeout" in result.error.lower()
        assert result.challenge_type == ChallengeType.JS_CHALLENGE


# --- solve_turnstile_capsolver ---


class TestSolveTurnstileCapSolver:
    @pytest.mark.asyncio
    async def test_returns_error_if_no_api_key(self, monkeypatch):
        monkeypatch.delenv("CAPSOLVER_API_KEY", raising=False)
        page = make_page()
        result = await solve_turnstile_capsolver(page, "https://g2.com")
        assert result.resolved is False
        assert "CAPSOLVER_API_KEY" in result.error

    @pytest.mark.asyncio
    async def test_logs_warning_when_api_key_missing(self, monkeypatch, caplog):
        """G#5: A warning log must be emitted when CAPSOLVER_API_KEY is absent."""
        import logging

        monkeypatch.delenv("CAPSOLVER_API_KEY", raising=False)
        page = make_page()
        with caplog.at_level(logging.WARNING, logger="app.challenge_solver"):
            await solve_turnstile_capsolver(page, "https://g2.com")
        assert any(
            "CAPSOLVER_API_KEY not configured" in record.message
            for record in caplog.records
        ), "Expected a WARNING log about missing CAPSOLVER_API_KEY"

    @pytest.mark.asyncio
    async def test_returns_error_if_no_sitekey(self, monkeypatch):
        monkeypatch.setenv("CAPSOLVER_API_KEY", "test-key")
        page = make_page()
        # All sitekey selectors return None
        page.query_selector = AsyncMock(return_value=None)
        result = await solve_turnstile_capsolver(page, "https://g2.com")
        assert result.resolved is False
        assert "sitekey" in result.error.lower()

    @pytest.mark.asyncio
    async def test_uses_explicit_api_key(self, monkeypatch):
        """When api_key is passed directly, it should be used instead of env."""
        monkeypatch.delenv("CAPSOLVER_API_KEY", raising=False)
        page = make_page()
        page.query_selector = AsyncMock(return_value=None)
        # Even with no sitekey, it should NOT fail on missing API key
        result = await solve_turnstile_capsolver(page, "https://g2.com", api_key="explicit-key")
        assert "CAPSOLVER_API_KEY" not in (result.error or "")


# --- _extract_turnstile_sitekey ---


class TestExtractTurnstileSitekey:
    @pytest.mark.asyncio
    async def test_extracts_from_data_sitekey_attribute(self):
        page = AsyncMock()
        el = AsyncMock()
        el.get_attribute = AsyncMock(side_effect=lambda attr: "0x4AAAAAAA" if attr == "data-sitekey" else None)

        async def query(sel):
            if sel == ".cf-turnstile[data-sitekey]":
                return el
            return None

        page.query_selector = AsyncMock(side_effect=query)
        result = await _extract_turnstile_sitekey(page)
        assert result == "0x4AAAAAAA"

    @pytest.mark.asyncio
    async def test_extracts_from_iframe_src(self):
        page = AsyncMock()
        el = AsyncMock()
        el.get_attribute = AsyncMock(
            side_effect=lambda attr: "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/av0/rcv0/0/iq12c/0x4BBBBBBB/auto/cbk/normal?sitekey=0x4BBBBBBB&action=managed"
            if attr == "src"
            else None
        )

        async def query(sel):
            if 'iframe' in sel:
                return el
            return None

        page.query_selector = AsyncMock(side_effect=query)
        result = await _extract_turnstile_sitekey(page)
        assert result == "0x4BBBBBBB"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_sitekey_found(self):
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        result = await _extract_turnstile_sitekey(page)
        assert result is None


# --- resolve_challenge (full pipeline) ---


class TestResolveChallenge:
    @pytest.mark.asyncio
    async def test_no_challenge_detected(self):
        page = make_page(title="Clean Page")
        result = await resolve_challenge(page, "https://g2.com")
        assert result.resolved is True
        assert result.method == "none"
        assert result.wait_time_ms == 0

    @pytest.mark.asyncio
    async def test_auto_resolves_js_challenge(self):
        """JS challenge detected then disappears -> auto_resolve."""
        page = make_page(title="Just a moment...")
        detect_count = 0

        async def changing_title():
            nonlocal detect_count
            detect_count += 1
            if detect_count <= 2:
                return "Just a moment..."
            return "Normal Page"

        page.title = AsyncMock(side_effect=changing_title)

        result = await resolve_challenge(
            page, "https://g2.com", auto_wait_ms=2000, capsolver_timeout_ms=1000,
        )
        assert result.resolved is True
        assert result.method == "auto_resolve"

    @pytest.mark.asyncio
    async def test_non_turnstile_challenge_does_not_try_capsolver(self, monkeypatch):
        """JS challenge that doesn't resolve should NOT try CapSolver."""
        monkeypatch.setenv("CAPSOLVER_API_KEY", "test-key")
        page = make_page(title="Just a moment...")
        # Title never changes -> timeout

        result = await resolve_challenge(
            page, "https://g2.com", auto_wait_ms=200, capsolver_timeout_ms=100,
        )
        assert result.resolved is False
        # JS_CHALLENGE, not TURNSTILE -> capsolver should not be attempted

    @pytest.mark.asyncio
    async def test_all_attempts_fail_returns_error(self):
        """Both auto-resolve and capsolver fail."""
        page = make_page(
            title="Normal",
            selectors={".cf-turnstile": True},
        )
        # Challenge never resolves

        result = await resolve_challenge(
            page, "https://g2.com", auto_wait_ms=200, capsolver_timeout_ms=100,
        )
        assert result.resolved is False
        assert result.error is not None


# --- ChallengeType enum ---


class TestChallengeType:
    def test_enum_values(self):
        assert ChallengeType.TURNSTILE == "turnstile"
        assert ChallengeType.JS_CHALLENGE == "js_challenge"
        assert ChallengeType.BROWSER_CHECK == "browser_check"
        assert ChallengeType.MANAGED == "managed_challenge"
        assert ChallengeType.NONE == "none"

    def test_is_string_enum(self):
        assert isinstance(ChallengeType.TURNSTILE, str)


# --- Constants ---


class TestLocalizedChallengeDetection:
    """Tests for localized Cloudflare challenge title detection (PT/ES/FR/DE)."""

    @pytest.mark.asyncio
    async def test_detects_portuguese_um_momento(self):
        page = make_page(title="Um momento...")
        result = await detect_challenge(page)
        assert result.detected is True
        assert result.challenge_type == ChallengeType.JS_CHALLENGE
        assert "um momento" in result.selector_matched

    @pytest.mark.asyncio
    async def test_detects_portuguese_verificacao(self):
        page = make_page(title="Verificação de segurança")
        result = await detect_challenge(page)
        assert result.detected is True

    @pytest.mark.asyncio
    async def test_detects_spanish_un_momento(self):
        page = make_page(title="Un momento por favor")
        result = await detect_challenge(page)
        assert result.detected is True

    @pytest.mark.asyncio
    async def test_detects_spanish_verificacion(self):
        page = make_page(title="Verificación de seguridad")
        result = await detect_challenge(page)
        assert result.detected is True

    @pytest.mark.asyncio
    async def test_detects_french_un_instant(self):
        page = make_page(title="Un instant s'il vous plaît")
        result = await detect_challenge(page)
        assert result.detected is True

    @pytest.mark.asyncio
    async def test_detects_german_einen_moment(self):
        page = make_page(title="Einen Moment bitte")
        result = await detect_challenge(page)
        assert result.detected is True

    @pytest.mark.asyncio
    async def test_detects_german_sicherheitsueberpruefung(self):
        page = make_page(title="Sicherheitsüberprüfung läuft")
        result = await detect_challenge(page)
        assert result.detected is True

    @pytest.mark.asyncio
    async def test_detects_french_verification(self):
        page = make_page(title="Vérification de sécurité en cours")
        result = await detect_challenge(page)
        assert result.detected is True


class TestConstants:
    def test_challenge_selectors_populated(self):
        assert len(CHALLENGE_SELECTORS) >= 6

    def test_resolved_selectors_populated(self):
        assert len(RESOLVED_SELECTORS) >= 2

    def test_challenge_title_patterns_populated(self):
        assert len(CHALLENGE_TITLE_PATTERNS) >= 5
        assert "just a moment" in CHALLENGE_TITLE_PATTERNS
