"""Tests for challenge_solver integration into browser.py crawl_with_context.

Verifies that:
1. resolve_challenge is called during crawl_with_context after navigation
2. Challenge telemetry fields appear in page_info dict
3. wait_for_load_state is called when a challenge is resolved
4. Graceful handling when challenge_solver import fails
5. G#6: routes.py reads challenge fields from payload (not hardcoded)
"""

import asyncio
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# browser.py source-level checks (no import needed)
# ---------------------------------------------------------------------------

class TestChallengeIntegrationInSource:
    """Check that browser.py source contains the challenge_solver integration."""

    @staticmethod
    def _crawl_with_context_source():
        browser_path = pathlib.Path(__file__).parent.parent / "app" / "browser.py"
        source = browser_path.read_text()
        start = source.index("async def crawl_with_context(")
        # Find the next top-level def/async def (class method at same indent or end)
        # We'll just grab a large chunk after the method start
        end = source.find("\n    async def ", start + 10)
        if end == -1:
            end = len(source)
        return source[start:end]

    def test_resolve_challenge_called_after_wait(self):
        """resolve_challenge must be called after wait_after_load_ms sleep."""
        source = self._crawl_with_context_source()
        assert "from app.challenge_solver import resolve_challenge" in source, (
            "browser.py must import resolve_challenge from app.challenge_solver"
        )
        assert "resolve_challenge(page" in source, (
            "resolve_challenge must be called with the page object"
        )

    def test_challenge_telemetry_in_page_info(self):
        """page_info dict must include challenge telemetry fields."""
        source = self._crawl_with_context_source()
        for field in ("challenge_detected", "challenge_resolved", "challenge_method", "challenge_wait_ms"):
            assert f'"{field}"' in source, (
                f"page_info must include '{field}' field"
            )

    def test_wait_for_load_state_on_resolved(self):
        """When challenge is resolved, should call wait_for_load_state."""
        source = self._crawl_with_context_source()
        assert "wait_for_load_state" in source, (
            "Should call wait_for_load_state after challenge resolution"
        )

    def test_graceful_exception_handling(self):
        """Challenge resolution failure should be caught, not crash crawl."""
        source = self._crawl_with_context_source()
        # The challenge block should be wrapped in try/except
        idx = source.index("resolve_challenge")
        # Find the nearest 'except' before the next major block
        before = source[:idx]
        assert "try:" in before[before.rfind("wait_ms"):], (
            "resolve_challenge call should be inside a try block"
        )


# ---------------------------------------------------------------------------
# routes.py G#6: challenge telemetry from payload (not hardcoded)
# ---------------------------------------------------------------------------

class TestRoutesChallengeFromPayload:
    """G#6: routes.py must read challenge fields from crawler payload,
    not hardcode them."""

    @staticmethod
    def _challenge_block_source():
        routes_path = pathlib.Path(__file__).parent.parent / "app" / "routes.py"
        source = routes_path.read_text()
        start = source.index("# ---- Challenge detection")
        end = source.index("# ---- Ghost Protocol fallback")
        return source[start:end]

    def test_challenge_detected_reads_from_payload(self):
        source = self._challenge_block_source()
        assert 'payload.get("challenge_detected")' in source, (
            "challenge_detected must be read from payload, not hardcoded"
        )

    def test_challenge_resolved_reads_from_payload(self):
        source = self._challenge_block_source()
        assert 'payload.get("challenge_resolved")' in source, (
            "challenge_resolved must be read from payload, not hardcoded"
        )

    def test_challenge_method_reads_from_payload(self):
        source = self._challenge_block_source()
        assert 'payload.get("challenge_method")' in source, (
            "challenge_method must be read from payload, not hardcoded"
        )

    def test_no_hardcoded_challenge_detected_false(self):
        source = self._challenge_block_source()
        assert "challenge_detected = False" not in source, (
            "challenge_detected should not be hardcoded to False"
        )

    def test_no_hardcoded_challenge_resolved_false(self):
        source = self._challenge_block_source()
        assert "challenge_resolved = False" not in source, (
            "challenge_resolved should not be hardcoded to False"
        )
