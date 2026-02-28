"""Tests for warmup_navigator -- Google search warm-up navigation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.warmup_navigator import (
    warmup_via_google,
    build_warmup_query,
    PLATFORM_DOMAINS,
)


# --- build_warmup_query ---


class TestBuildWarmupQuery:
    def test_trustpilot_query(self):
        """Should build a site-restricted query for trustpilot."""
        q = build_warmup_query("Acme Corp", "trustpilot")
        assert q == '"Acme Corp" reviews site:trustpilot.com'

    def test_g2_query(self):
        """Should build a site-restricted query for g2."""
        q = build_warmup_query("Slack", "g2")
        assert q == '"Slack" reviews site:g2.com'

    def test_capterra_query(self):
        q = build_warmup_query("Jira", "capterra")
        assert q == '"Jira" reviews site:capterra.com'

    def test_trustradius_query(self):
        q = build_warmup_query("Salesforce", "trustradius")
        assert q == '"Salesforce" reviews site:trustradius.com'

    def test_unknown_platform_omits_site(self):
        """Unknown platform should produce a query without site: restriction."""
        q = build_warmup_query("SomeProduct", "unknownplatform")
        assert q == '"SomeProduct" reviews'
        assert "site:" not in q

    def test_query_includes_competitor_name(self):
        q = build_warmup_query("My Product", "g2")
        assert '"My Product"' in q


# --- PLATFORM_DOMAINS ---


class TestPlatformDomains:
    def test_has_trustpilot(self):
        assert PLATFORM_DOMAINS["trustpilot"] == "trustpilot.com"

    def test_has_g2(self):
        assert PLATFORM_DOMAINS["g2"] == "g2.com"

    def test_has_capterra(self):
        assert PLATFORM_DOMAINS["capterra"] == "capterra.com"

    def test_has_trustradius(self):
        assert PLATFORM_DOMAINS["trustradius"] == "trustradius.com"


# --- warmup_via_google ---


def _make_mock_page(url_after_click="https://www.trustpilot.com/review/acme"):
    """Create a mock Playwright page with configurable behavior."""
    page = AsyncMock()
    page.goto = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[])
    page.url = url_after_click
    page.wait_for_load_state = AsyncMock()
    return page


def _make_mock_link():
    """Create a mock link element that can be clicked."""
    link = AsyncMock()
    link.click = AsyncMock()
    return link


@pytest.mark.asyncio
class TestWarmupViaGoogle:
    async def test_navigates_to_google_with_encoded_query(self):
        """Should navigate to Google with URL-encoded search query."""
        page = _make_mock_page()
        search_query = '"Acme Corp" reviews site:trustpilot.com'

        await warmup_via_google(page, "https://www.trustpilot.com/review/acme", search_query)

        page.goto.assert_called_once()
        goto_url = page.goto.call_args[0][0]
        assert goto_url.startswith("https://www.google.com/search?q=")
        # Query should be URL-encoded
        assert "%22Acme" in goto_url or "%22acme" in goto_url.lower()

    async def test_clicks_matching_link_when_found(self):
        """When a matching link is found in Google results, click it."""
        page = _make_mock_page()
        mock_link = _make_mock_link()
        page.query_selector_all = AsyncMock(return_value=[mock_link])

        result = await warmup_via_google(
            page,
            "https://www.trustpilot.com/review/acme",
            '"Acme" reviews site:trustpilot.com',
        )

        assert result is True
        mock_link.click.assert_called_once()

    async def test_returns_false_when_no_matching_link(self):
        """When no matching link is found, return False."""
        page = _make_mock_page()
        page.query_selector_all = AsyncMock(return_value=[])

        result = await warmup_via_google(
            page,
            "https://www.trustpilot.com/review/acme",
            '"Acme" reviews site:trustpilot.com',
        )

        assert result is False

    async def test_graceful_fallback_on_timeout(self):
        """On timeout exception, return False without raising."""
        page = _make_mock_page()
        page.goto = AsyncMock(side_effect=TimeoutError("Navigation timeout"))

        result = await warmup_via_google(
            page,
            "https://www.trustpilot.com/review/acme",
            '"Acme" reviews',
        )

        assert result is False

    async def test_graceful_fallback_on_generic_exception(self):
        """On any exception, return False without raising."""
        page = _make_mock_page()
        page.goto = AsyncMock(side_effect=Exception("Connection refused"))

        result = await warmup_via_google(
            page,
            "https://www.trustpilot.com/review/acme",
            '"Acme" reviews',
        )

        assert result is False

    async def test_domain_matching_extracts_correctly(self):
        """Should extract domain from target_url and use it in selector query."""
        page = _make_mock_page()

        await warmup_via_google(
            page,
            "https://www.trustpilot.com/review/acme",
            '"Acme" reviews site:trustpilot.com',
        )

        # query_selector_all should be called with a selector matching the domain
        page.query_selector_all.assert_called_once()
        selector = page.query_selector_all.call_args[0][0]
        assert "trustpilot.com" in selector

    async def test_strips_www_from_domain(self):
        """www. prefix should be stripped from domain for broader matching."""
        page = _make_mock_page()

        await warmup_via_google(
            page,
            "https://www.g2.com/products/slack/reviews",
            '"Slack" reviews site:g2.com',
        )

        selector = page.query_selector_all.call_args[0][0]
        assert "www." not in selector
        assert "g2.com" in selector

    async def test_returns_false_for_invalid_target_url(self):
        """If target URL has no domain, return False."""
        page = _make_mock_page()

        result = await warmup_via_google(
            page,
            "not-a-valid-url",
            '"Acme" reviews',
        )

        assert result is False

    async def test_waits_after_google_page_load(self):
        """Should wait a random delay after loading Google page."""
        page = _make_mock_page()

        with patch("app.warmup_navigator.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await warmup_via_google(
                page,
                "https://www.trustpilot.com/review/acme",
                '"Acme" reviews',
            )

            # Should sleep at least once (the post-load delay)
            mock_sleep.assert_called()
            delay = mock_sleep.call_args_list[0][0][0]
            assert 1.0 <= delay <= 2.5

    async def test_wait_for_load_state_after_click(self):
        """After clicking a link, should wait for page load."""
        page = _make_mock_page()
        mock_link = _make_mock_link()
        page.query_selector_all = AsyncMock(return_value=[mock_link])

        await warmup_via_google(
            page,
            "https://www.trustpilot.com/review/acme",
            '"Acme" reviews',
        )

        page.wait_for_load_state.assert_called_once_with(
            "domcontentloaded", timeout=12000
        )

    async def test_load_state_timeout_does_not_fail(self):
        """If wait_for_load_state times out, should still return True."""
        page = _make_mock_page()
        mock_link = _make_mock_link()
        page.query_selector_all = AsyncMock(return_value=[mock_link])
        page.wait_for_load_state = AsyncMock(
            side_effect=Exception("Timeout waiting for load state")
        )

        result = await warmup_via_google(
            page,
            "https://www.trustpilot.com/review/acme",
            '"Acme" reviews',
        )

        # Still returns True because the click happened
        assert result is True

    async def test_custom_timeout(self):
        """Custom timeout_ms is passed to page.goto."""
        page = _make_mock_page()

        await warmup_via_google(
            page,
            "https://www.trustpilot.com/review/acme",
            '"Acme" reviews',
            timeout_ms=5000,
        )

        _, kwargs = page.goto.call_args
        assert kwargs.get("timeout") == 5000
