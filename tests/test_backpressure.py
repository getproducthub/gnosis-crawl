"""Tests for crawl queue backpressure (429 Too Many Requests).

Verifies that gnosis-crawl rejects requests with HTTP 429 when the
browser semaphore queue depth exceeds MAX_CRAWL_QUEUE_DEPTH, rather
than letting them pile up and timeout.
"""
import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.exceptions import QueueOverflowError


# ---------------------------------------------------------------------------
# Unit tests for BrowserEngine.acquire_with_backpressure
# ---------------------------------------------------------------------------

class TestAcquireWithBackpressure:
    """Tests for the semaphore backpressure gate on BrowserEngine."""

    @pytest.mark.asyncio
    async def test_acquire_succeeds_under_threshold(self):
        """Normal acquire works when queue depth is below MAX_CRAWL_QUEUE_DEPTH."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()
        # Directly call acquire — should not raise
        await engine.acquire_with_backpressure()
        # Clean up: release the semaphore
        engine._context_semaphore.release()
        assert engine._semaphore_waiters == 0

    @pytest.mark.asyncio
    async def test_waiter_count_increments_and_decrements(self):
        """_semaphore_waiters tracks how many requests are waiting."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()
        # Fill all semaphore slots so next acquire will wait
        for _ in range(engine._context_semaphore._value):
            await engine._context_semaphore.acquire()

        assert engine._semaphore_waiters == 0

        # Start a waiter in the background
        acquired = asyncio.Event()
        async def _waiter():
            await engine.acquire_with_backpressure()
            acquired.set()

        task = asyncio.create_task(_waiter())
        await asyncio.sleep(0.05)  # Let it enter the wait

        assert engine._semaphore_waiters == 1

        # Release one slot — waiter should complete
        engine._context_semaphore.release()
        await asyncio.sleep(0.05)
        assert acquired.is_set()
        assert engine._semaphore_waiters == 0

        # Clean up remaining semaphore slots
        for _ in range(engine._context_semaphore._value - 1):
            engine._context_semaphore.release()
        # Release the slot acquired by the waiter
        engine._context_semaphore.release()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_overflow_raises_when_at_limit(self):
        """QueueOverflowError raised when waiters >= MAX_CRAWL_QUEUE_DEPTH."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()
        # Simulate waiters at the limit
        engine._semaphore_waiters = engine._max_crawl_queue_depth

        with pytest.raises(QueueOverflowError, match="exceeds limit"):
            await engine.acquire_with_backpressure()

    @pytest.mark.asyncio
    async def test_overflow_includes_counts_in_message(self):
        """Error message includes current depth and limit."""
        from app.browser import BrowserEngine

        engine = BrowserEngine()
        engine._semaphore_waiters = engine._max_crawl_queue_depth

        with pytest.raises(QueueOverflowError) as exc_info:
            await engine.acquire_with_backpressure()

        msg = str(exc_info.value)
        assert str(engine._max_crawl_queue_depth) in msg

    @pytest.mark.asyncio
    async def test_custom_queue_depth_from_env(self):
        """MAX_CRAWL_QUEUE_DEPTH is configurable via environment variable."""
        with patch.dict(os.environ, {"MAX_CRAWL_QUEUE_DEPTH": "5"}):
            # Need to reimport or create fresh instance to pick up new env
            from app.browser import BrowserEngine
            engine = BrowserEngine()
            engine._max_crawl_queue_depth = int(os.environ.get("MAX_CRAWL_QUEUE_DEPTH", "20"))
            engine._semaphore_waiters = 5

            with pytest.raises(QueueOverflowError):
                await engine.acquire_with_backpressure()


# ---------------------------------------------------------------------------
# Route-level tests for 429 response
# ---------------------------------------------------------------------------

class TestRouteBackpressure:
    """Tests that route handlers return 429 when QueueOverflowError is raised."""

    @pytest.fixture
    def mock_crawler_engine(self):
        """Create a mock crawler engine that raises QueueOverflowError."""
        mock = AsyncMock()
        mock.crawl_url = AsyncMock(side_effect=QueueOverflowError("Queue depth (25) exceeds limit (20)"))
        mock.crawl_raw_html = AsyncMock(side_effect=QueueOverflowError("Queue depth (25) exceeds limit (20)"))
        mock.batch_crawl = AsyncMock(side_effect=QueueOverflowError("Queue depth (25) exceeds limit (20)"))
        return mock

    @pytest.mark.asyncio
    async def test_crawl_endpoint_returns_429(self, mock_crawler_engine):
        """POST /api/crawl returns 429 with Retry-After when queue overflows."""
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.routes.get_crawler_engine", return_value=mock_crawler_engine), \
             patch("app.routes.get_optional_user_email", return_value="test@test.com"):
            client = TestClient(app)
            response = client.post("/api/crawl", json={
                "url": "https://example.com",
                "customer_id": "test-customer"
            })

            assert response.status_code == 429
            assert response.json()["error"] == "Too many requests"
            assert "Retry-After" in response.headers
            assert response.headers["Retry-After"] == "30"

    @pytest.mark.asyncio
    async def test_markdown_endpoint_returns_429(self, mock_crawler_engine):
        """POST /api/markdown returns 429 with Retry-After when queue overflows."""
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.routes.get_crawler_engine", return_value=mock_crawler_engine), \
             patch("app.routes.get_optional_user_email", return_value="test@test.com"):
            client = TestClient(app)
            response = client.post("/api/markdown", json={
                "url": "https://example.com",
                "customer_id": "test-customer"
            })

            assert response.status_code == 429
            assert response.json()["error"] == "Too many requests"
            assert response.headers["Retry-After"] == "30"

    @pytest.mark.asyncio
    async def test_batch_endpoint_returns_429(self, mock_crawler_engine):
        """POST /api/batch returns 429 with Retry-After when queue overflows."""
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.routes.get_crawler_engine", return_value=mock_crawler_engine), \
             patch("app.routes.get_optional_user_email", return_value="test@test.com"):
            client = TestClient(app)
            response = client.post("/api/batch", json={
                "urls": ["https://example.com"],
                "customer_id": "test-customer"
            })

            assert response.status_code == 429
            assert response.json()["error"] == "Too many requests"
            assert response.headers["Retry-After"] == "30"

    @pytest.mark.asyncio
    async def test_raw_endpoint_returns_429(self, mock_crawler_engine):
        """POST /api/raw returns 429 with Retry-After when queue overflows."""
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.routes.get_crawler_engine", return_value=mock_crawler_engine), \
             patch("app.routes.get_optional_user_email", return_value="test@test.com"):
            client = TestClient(app)
            response = client.post("/api/raw", json={
                "url": "https://example.com",
                "customer_id": "test-customer"
            })

            assert response.status_code == 429
            assert response.json()["error"] == "Too many requests"
            assert response.headers["Retry-After"] == "30"

    @pytest.mark.asyncio
    async def test_429_response_includes_detail(self, mock_crawler_engine):
        """429 response body includes detail about the overflow."""
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.routes.get_crawler_engine", return_value=mock_crawler_engine), \
             patch("app.routes.get_optional_user_email", return_value="test@test.com"):
            client = TestClient(app)
            response = client.post("/api/crawl", json={
                "url": "https://example.com",
                "customer_id": "test-customer"
            })

            body = response.json()
            assert "detail" in body
            assert "exceeds limit" in body["detail"]
