"""Unit tests for app.models — Pydantic request/response models."""

import pytest
from pydantic import ValidationError

from app.models import (
    AgentRunRequest,
    AgentRunResponse,
    AgentStatusResponse,
    AgentTraceEntry,
    BatchRequest,
    CacheSearchRequest,
    CachePruneRequest,
    CacheUpsertRequest,
    CrawlOptions,
    CrawlRequest,
    GhostExtractRequest,
    GhostExtractResponse,
    MarkdownRequest,
    RawHtmlRequest,
)


class TestCrawlOptions:
    def test_defaults(self):
        opts = CrawlOptions()
        assert opts.javascript is True
        assert opts.screenshot is False
        assert opts.timeout == 30
        assert opts.wait_until == "domcontentloaded"

    def test_timeout_bounds(self):
        with pytest.raises(ValidationError):
            CrawlOptions(timeout=1)  # below 5
        with pytest.raises(ValidationError):
            CrawlOptions(timeout=999)  # above 300


class TestCrawlRequest:
    def test_valid(self):
        r = CrawlRequest(url="https://example.com")
        assert str(r.url) == "https://example.com/"

    def test_invalid_url(self):
        with pytest.raises(ValidationError):
            CrawlRequest(url="not-a-url")


class TestMarkdownRequest:
    def test_single_url(self):
        r = MarkdownRequest(url="https://example.com")
        assert r.url is not None

    def test_multiple_urls(self):
        r = MarkdownRequest(urls=["https://a.com", "https://b.com"])
        assert len(r.urls) == 2

    def test_requires_url_or_urls(self):
        with pytest.raises(ValidationError):
            MarkdownRequest()


class TestBatchRequest:
    def test_valid(self):
        r = BatchRequest(urls=["https://a.com", "https://b.com"])
        assert len(r.urls) == 2
        assert r.concurrent == 3

    def test_concurrent_bounds(self):
        with pytest.raises(ValidationError):
            BatchRequest(urls=["https://a.com"], concurrent=0)
        with pytest.raises(ValidationError):
            BatchRequest(urls=["https://a.com"], concurrent=99)


class TestAgentRunRequest:
    def test_valid(self):
        r = AgentRunRequest(task="Find pricing on example.com")
        assert r.task == "Find pricing on example.com"
        assert r.max_steps == 12
        assert r.max_wall_time_ms == 90_000

    def test_empty_task_rejected(self):
        with pytest.raises(ValidationError):
            AgentRunRequest(task="")

    def test_task_max_length(self):
        with pytest.raises(ValidationError):
            AgentRunRequest(task="x" * 4001)

    def test_custom_limits(self):
        r = AgentRunRequest(task="test", max_steps=5, max_wall_time_ms=30000)
        assert r.max_steps == 5
        assert r.max_wall_time_ms == 30000

    def test_allowed_domains(self):
        r = AgentRunRequest(task="test", allowed_domains=["example.com", "test.com"])
        assert len(r.allowed_domains) == 2

    def test_step_bounds(self):
        with pytest.raises(ValidationError):
            AgentRunRequest(task="test", max_steps=0)
        with pytest.raises(ValidationError):
            AgentRunRequest(task="test", max_steps=100)


class TestAgentRunResponse:
    def test_success_response(self):
        r = AgentRunResponse(
            success=True,
            run_id="abc123",
            stop_reason="completed",
            response="Found 3 plans",
            steps=4,
            wall_time_ms=12000,
        )
        assert r.success is True
        assert r.trace == []

    def test_failed_response(self):
        r = AgentRunResponse(
            success=False,
            run_id="abc123",
            stop_reason="max_failures",
            error="3 consecutive failures",
        )
        assert r.success is False
        assert r.error is not None


class TestAgentStatusResponse:
    def test_not_found(self):
        r = AgentStatusResponse(run_id="abc", found=False)
        assert r.found is False
        assert r.success is None

    def test_found(self):
        r = AgentStatusResponse(
            run_id="abc",
            found=True,
            success=True,
            stop_reason="completed",
            steps=3,
        )
        assert r.found is True
        assert r.success is True


class TestAgentTraceEntry:
    def test_all_optional(self):
        e = AgentTraceEntry()
        assert e.event is None
        assert e.step_id is None

    def test_with_values(self):
        e = AgentTraceEntry(event="tool_dispatch", step_id=2, tool_name="crawl", duration_ms=150)
        assert e.tool_name == "crawl"


class TestGhostExtractRequest:
    def test_valid(self):
        r = GhostExtractRequest(url="https://example.com")
        assert r.timeout == 30

    def test_empty_url_rejected(self):
        with pytest.raises(ValidationError):
            GhostExtractRequest(url="")

    def test_timeout_bounds(self):
        with pytest.raises(ValidationError):
            GhostExtractRequest(url="https://example.com", timeout=1)
        with pytest.raises(ValidationError):
            GhostExtractRequest(url="https://example.com", timeout=999)

    def test_custom_prompt(self):
        r = GhostExtractRequest(url="https://example.com", prompt="Extract all prices")
        assert r.prompt == "Extract all prices"


class TestGhostExtractResponse:
    def test_success(self):
        r = GhostExtractResponse(
            success=True,
            url="https://example.com",
            content="Extracted text here",
            capture_ms=500,
            extraction_ms=2000,
            total_ms=2500,
            provider="OpenAIAdapter",
        )
        assert r.render_mode == "ghost"
        assert r.blocked_content is False

    def test_failure(self):
        r = GhostExtractResponse(
            success=False,
            url="https://example.com",
            error="Vision provider failed",
        )
        assert r.content is None


class TestCacheModels:
    def test_search_request_defaults(self):
        r = CacheSearchRequest(query="test")
        assert r.min_similarity == 0.4
        assert r.max_results == 20

    def test_upsert_request(self):
        r = CacheUpsertRequest(url="https://example.com", markdown="# Hello")
        assert r.quality == "sufficient"

    def test_prune_request(self):
        r = CachePruneRequest(dry_run=True)
        assert r.dry_run is True
        assert r.domain is None
