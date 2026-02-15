"""Unit tests for app.observability — EventBus and TraceCollector."""

import pytest

from app.agent.types import RunConfig, RunResult, StopReason, ToolCall, ToolResult
from app.observability.events import (
    EventBus,
    EventKind,
    PolicyDeniedEvent,
    RunEndEvent,
    RunStartEvent,
    StepEndEvent,
    StepStartEvent,
    ToolDispatchEvent,
    ToolResultEvent,
)
from app.observability.trace import RunSummary, TraceCollector
from app.agent.types import RunState


class TestEventKind:
    def test_all_kinds(self):
        assert EventKind.RUN_START == "run_start"
        assert EventKind.STEP_START == "step_start"
        assert EventKind.TOOL_DISPATCH == "tool_dispatch"
        assert EventKind.TOOL_RESULT == "tool_result"
        assert EventKind.POLICY_DENIED == "policy_denied"
        assert EventKind.STEP_END == "step_end"
        assert EventKind.RUN_END == "run_end"


class TestEventBus:
    def test_emit_and_receive(self):
        bus = EventBus()
        received = []

        bus.on(EventKind.RUN_START, lambda e: received.append(e))
        bus.emit(RunStartEvent(run_id="abc", task="test", config=RunConfig()))

        assert len(received) == 1
        assert received[0].run_id == "abc"

    def test_on_all(self):
        bus = EventBus()
        received = []

        bus.on_all(lambda e: received.append(e))
        bus.emit(RunStartEvent(run_id="abc", task="test", config=RunConfig()))
        bus.emit(RunEndEvent(run_id="abc", success=True, stop_reason=StopReason.COMPLETED, steps=1, wall_time_ms=100))

        assert len(received) == 2

    def test_multiple_listeners(self):
        bus = EventBus()
        a, b = [], []

        bus.on(EventKind.RUN_START, lambda e: a.append(e))
        bus.on(EventKind.RUN_START, lambda e: b.append(e))
        bus.emit(RunStartEvent(run_id="abc", task="test", config=RunConfig()))

        assert len(a) == 1
        assert len(b) == 1

    def test_wrong_kind_not_received(self):
        bus = EventBus()
        received = []

        bus.on(EventKind.RUN_END, lambda e: received.append(e))
        bus.emit(RunStartEvent(run_id="abc", task="test", config=RunConfig()))

        assert len(received) == 0


class TestEvents:
    def test_run_start_event(self):
        e = RunStartEvent(run_id="abc", task="test task", config=RunConfig())
        assert e.kind == EventKind.RUN_START
        assert e.task == "test task"

    def test_step_start_event(self):
        e = StepStartEvent(run_id="abc", step_id=1, state=RunState.PLAN)
        assert e.kind == EventKind.STEP_START
        assert e.step_id == 1

    def test_tool_dispatch_event(self):
        tc = ToolCall(id="1", name="crawl", args={"url": "https://example.com"})
        e = ToolDispatchEvent(run_id="abc", step_id=1, tool_call=tc)
        assert e.kind == EventKind.TOOL_DISPATCH
        assert e.tool_call.name == "crawl"

    def test_tool_result_event(self):
        tr = ToolResult(tool_call_id="1", ok=True, payload="data")
        e = ToolResultEvent(run_id="abc", step_id=1, tool_result=tr)
        assert e.kind == EventKind.TOOL_RESULT
        assert e.tool_result.ok is True

    def test_policy_denied_event(self):
        e = PolicyDeniedEvent(run_id="abc", step_id=1, tool_name="evil", reason="blocked", flags=["private_ip"])
        assert e.kind == EventKind.POLICY_DENIED
        assert e.tool_name == "evil"

    def test_step_end_event(self):
        e = StepEndEvent(run_id="abc", step_id=1, duration_ms=150)
        assert e.kind == EventKind.STEP_END
        assert e.duration_ms == 150

    def test_run_end_event(self):
        e = RunEndEvent(run_id="abc", success=True, stop_reason=StopReason.COMPLETED, steps=3, wall_time_ms=5000)
        assert e.kind == EventKind.RUN_END
        assert e.success is True


class TestTraceCollector:
    def test_attach_and_collect(self):
        bus = EventBus()
        collector = TraceCollector(run_id="abc", redact=False)
        collector.attach(bus)

        bus.emit(RunStartEvent(run_id="abc", task="test", config=RunConfig()))
        bus.emit(StepStartEvent(run_id="abc", step_id=1, state=RunState.PLAN))
        bus.emit(StepEndEvent(run_id="abc", step_id=1, duration_ms=100))
        bus.emit(RunEndEvent(run_id="abc", success=True, stop_reason=StopReason.COMPLETED, steps=1, wall_time_ms=200))

        result = RunResult(
            run_id="abc",
            success=True,
            stop_reason=StopReason.COMPLETED,
            response="done",
            steps=1,
            wall_time_ms=200,
        )
        summary = collector.finalize(result)

        assert summary.run_id == "abc"
        assert summary.success is True
        assert summary.steps == 1
        assert len(summary.trace) > 0

    def test_finalize_produces_run_summary(self):
        collector = TraceCollector(run_id="test123", redact=False)
        result = RunResult(
            run_id="test123",
            success=False,
            stop_reason=StopReason.MAX_STEPS,
            error="hit limit",
            steps=12,
            wall_time_ms=90000,
        )
        summary = collector.finalize(result)

        assert isinstance(summary, RunSummary)
        assert summary.run_id == "test123"
        assert summary.success is False
        assert summary.stop_reason == "max_steps"
        assert summary.error == "hit limit"


class TestRunSummary:
    def test_to_dict(self):
        summary = RunSummary(
            run_id="abc",
            task="test task",
            success=True,
            stop_reason="completed",
            steps=2,
            wall_time_ms=3000,
            failures=0,
            response="done",
            trace=[{"event": "run_start"}],
        )
        d = summary.to_dict()
        assert d["run_id"] == "abc"
        assert d["success"] is True
        assert d["steps"] == 2
        assert len(d["trace"]) == 1

    def test_to_json(self):
        summary = RunSummary(
            run_id="abc",
            task="test task",
            success=True,
            stop_reason="completed",
            steps=1,
            wall_time_ms=1000,
            failures=0,
            trace=[],
        )
        j = summary.to_json()
        assert '"run_id": "abc"' in j
        assert '"success": true' in j
