"""Unit tests for app.agent.types — core type primitives."""

import time
import pytest

from app.agent.types import (
    AssistantAction,
    Respond,
    RunConfig,
    RunContext,
    RunResult,
    RunState,
    StepResult,
    StepTrace,
    StopReason,
    ToolCall,
    ToolCalls,
    ToolResult,
)


class TestRunState:
    def test_all_states_exist(self):
        assert RunState.INIT == "init"
        assert RunState.PLAN == "plan"
        assert RunState.EXECUTE_TOOL == "execute_tool"
        assert RunState.OBSERVE == "observe"
        assert RunState.RESPOND == "respond"
        assert RunState.STOP == "stop"
        assert RunState.ERROR == "error"

    def test_state_is_string_enum(self):
        assert isinstance(RunState.INIT, str)
        assert RunState.INIT == "init"


class TestStopReason:
    def test_all_reasons_exist(self):
        assert StopReason.MAX_STEPS == "max_steps"
        assert StopReason.MAX_WALL_TIME == "max_wall_time"
        assert StopReason.MAX_FAILURES == "max_failures"
        assert StopReason.NO_OP_LOOP == "no_op_loop"
        assert StopReason.POLICY_DENIED == "policy_denied"
        assert StopReason.COMPLETED == "completed"


class TestToolCall:
    def test_frozen(self):
        tc = ToolCall(id="tc_1", name="crawl", args={"url": "https://example.com"})
        with pytest.raises(AttributeError):
            tc.name = "other"

    def test_fields(self):
        tc = ToolCall(id="tc_1", name="crawl", args={"url": "https://example.com"})
        assert tc.id == "tc_1"
        assert tc.name == "crawl"
        assert tc.args["url"] == "https://example.com"


class TestToolResult:
    def test_success_result(self):
        r = ToolResult(tool_call_id="tc_1", ok=True, payload={"data": 1})
        assert r.ok is True
        assert r.payload == {"data": 1}
        assert r.error_code is None
        assert r.duration_ms == 0

    def test_error_result(self):
        r = ToolResult(
            tool_call_id="tc_1",
            ok=False,
            error_code="timeout",
            error_message="timed out",
            retriable=True,
            duration_ms=30000,
        )
        assert r.ok is False
        assert r.retriable is True


class TestAssistantAction:
    def test_respond_is_action(self):
        action: AssistantAction = Respond(text="Hello")
        assert isinstance(action, Respond)
        assert action.text == "Hello"

    def test_tool_calls_is_action(self):
        calls = [ToolCall(id="1", name="crawl", args={})]
        action: AssistantAction = ToolCalls(calls=calls)
        assert isinstance(action, ToolCalls)
        assert len(action.calls) == 1


class TestRunConfig:
    def test_defaults(self):
        cfg = RunConfig()
        assert cfg.max_steps == 12
        assert cfg.max_wall_time_ms == 90_000
        assert cfg.max_failures == 3
        assert cfg.allowed_tools == []
        assert cfg.allowed_domains == []
        assert cfg.block_private_ranges is True
        assert cfg.redact_secrets is True

    def test_custom_values(self):
        cfg = RunConfig(max_steps=5, allowed_domains=["example.com"])
        assert cfg.max_steps == 5
        assert cfg.allowed_domains == ["example.com"]


class TestRunContext:
    def test_defaults(self):
        ctx = RunContext()
        assert ctx.state == RunState.INIT
        assert ctx.step == 0
        assert ctx.failures == 0
        assert ctx.messages == []
        assert len(ctx.run_id) == 16

    def test_elapsed_ms(self):
        ctx = RunContext()
        # Should be very small (just created)
        assert ctx.elapsed_ms >= 0
        assert ctx.elapsed_ms < 1000

    def test_unique_run_ids(self):
        ctx1 = RunContext()
        ctx2 = RunContext()
        assert ctx1.run_id != ctx2.run_id


class TestStepTrace:
    def test_defaults(self):
        t = StepTrace(run_id="abc", step_id=1, state=RunState.PLAN)
        assert t.status == "ok"
        assert t.tool_name is None
        assert t.duration_ms == 0

    def test_with_tool(self):
        t = StepTrace(
            run_id="abc",
            step_id=2,
            state=RunState.EXECUTE_TOOL,
            tool_name="crawl",
            duration_ms=150,
            status="ok",
        )
        assert t.tool_name == "crawl"


class TestRunResult:
    def test_success_result(self):
        r = RunResult(
            run_id="abc",
            success=True,
            stop_reason=StopReason.COMPLETED,
            response="Done",
            steps=3,
            wall_time_ms=5000,
        )
        assert r.success is True
        assert r.error is None

    def test_failed_result(self):
        r = RunResult(
            run_id="abc",
            success=False,
            stop_reason=StopReason.MAX_FAILURES,
            error="Too many failures",
        )
        assert r.success is False
        assert r.stop_reason == StopReason.MAX_FAILURES
