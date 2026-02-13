"""Agent engine: bounded loop runner for Mode B (internal micro-agent).

The engine implements:
  plan(ctx)  -> ask the LLM for the next action
  step(ctx)  -> execute that action (tool calls or respond)
  run_task() -> outer loop with stop-condition enforcement every iteration
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol

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
    ToolCalls,
    ToolResult,
)
from app.agent.errors import PolicyDeniedError, ProviderError, StopConditionError
from app.agent.dispatcher import Dispatcher
from app.policy.gate import check_tool_call, PolicyVerdict

logger = logging.getLogger(__name__)

NO_OP_THRESHOLD = 3  # consecutive empty/no-op responses before forced stop


# ---------------------------------------------------------------------------
# Provider protocol (W6 will supply concrete implementations)
# ---------------------------------------------------------------------------

class LLMAdapter(Protocol):
    """Minimal interface that every provider adapter must satisfy."""

    async def complete(self, messages: list[dict], tools: list[dict]) -> AssistantAction:
        """Send messages + tool schemas → get back an AssistantAction."""
        ...


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AgentEngine:
    """Bounded loop runner for Mode B."""

    def __init__(
        self,
        provider: LLMAdapter,
        dispatcher: Dispatcher,
        tool_schemas: list[dict],
    ):
        self.provider = provider
        self.dispatcher = dispatcher
        self.tool_schemas = tool_schemas

    # ------------------------------------------------------------------
    # Top-level entry point
    # ------------------------------------------------------------------

    async def run_task(
        self,
        task: str,
        config: Optional[RunConfig] = None,
    ) -> RunResult:
        """Execute a bounded agent loop and return the final result."""
        config = config or RunConfig()
        ctx = RunContext(task=task, config=config)

        # Seed the conversation with the task
        ctx.messages.append({"role": "user", "content": task})
        ctx.state = RunState.PLAN

        while ctx.state not in (RunState.STOP, RunState.ERROR):
            # --- stop-condition check (every iteration) ---
            stop = self._check_stop(ctx)
            if stop is not None:
                ctx.state = RunState.STOP
                return self._finalize(ctx, stop)

            try:
                step = await self._tick(ctx)
            except StopConditionError as exc:
                ctx.state = RunState.STOP
                return self._finalize(ctx, StopReason(exc.code) if exc.code in StopReason.__members__ else StopReason.COMPLETED, error=str(exc))
            except Exception as exc:
                logger.error("Engine tick failed: %s", exc, exc_info=True)
                ctx.state = RunState.ERROR
                return self._finalize(ctx, StopReason.COMPLETED, error=str(exc))

        return self._finalize(ctx, StopReason.COMPLETED)

    # ------------------------------------------------------------------
    # Single tick: plan → execute → observe
    # ------------------------------------------------------------------

    async def _tick(self, ctx: RunContext) -> StepResult:
        """One full plan→execute→observe cycle."""
        ctx.step += 1

        # PLAN: ask the LLM
        ctx.state = RunState.PLAN
        try:
            action = await self.provider.complete(ctx.messages, self.tool_schemas)
        except Exception as exc:
            ctx.failures += 1
            raise ProviderError(str(exc))

        # RESPOND path: terminal
        if isinstance(action, Respond):
            ctx.state = RunState.RESPOND
            ctx.messages.append({"role": "assistant", "content": action.text})
            ctx.consecutive_no_ops = 0
            trace = StepTrace(run_id=ctx.run_id, step_id=ctx.step, state=RunState.RESPOND)
            ctx.trace.append(trace)
            ctx.state = RunState.STOP
            return StepResult(action=action, stop_reason=StopReason.COMPLETED)

        # TOOL CALLS path
        if isinstance(action, ToolCalls):
            if not action.calls:
                ctx.consecutive_no_ops += 1
                return StepResult(action=action)

            ctx.consecutive_no_ops = 0
            ctx.state = RunState.EXECUTE_TOOL

            # Record assistant message with tool calls
            ctx.messages.append({
                "role": "assistant",
                "tool_calls": [
                    {"id": c.id, "name": c.name, "args": c.args}
                    for c in action.calls
                ],
            })

            results: list[ToolResult] = []
            for call in action.calls:
                # Policy gate
                verdict: PolicyVerdict = check_tool_call(call, ctx.config)
                if not verdict.allowed:
                    logger.warning("Policy denied tool %s: %s", call.name, verdict.reason)
                    results.append(ToolResult(
                        tool_call_id=call.id,
                        ok=False,
                        error_code="policy_denied",
                        error_message=verdict.reason,
                    ))
                    ctx.trace.append(StepTrace(
                        run_id=ctx.run_id,
                        step_id=ctx.step,
                        state=RunState.EXECUTE_TOOL,
                        tool_name=call.name,
                        status="policy_denied",
                        policy_flags=verdict.flags,
                    ))
                    continue

                # Dispatch
                result = await self.dispatcher.dispatch(call)
                results.append(result)

                status = "ok" if result.ok else (result.error_code or "error")
                ctx.trace.append(StepTrace(
                    run_id=ctx.run_id,
                    step_id=ctx.step,
                    state=RunState.EXECUTE_TOOL,
                    tool_name=call.name,
                    args_hash=Dispatcher.args_hash(call.args),
                    duration_ms=result.duration_ms,
                    status=status,
                    error_code=result.error_code,
                ))

                if not result.ok:
                    ctx.failures += 1

            # OBSERVE: feed results back into conversation
            ctx.state = RunState.OBSERVE
            for r in results:
                ctx.messages.append({
                    "role": "tool",
                    "tool_call_id": r.tool_call_id,
                    "content": r.payload if r.ok else f"ERROR [{r.error_code}]: {r.error_message}",
                })

            return StepResult(action=action, tool_results=results)

        # Shouldn't reach here
        raise ProviderError(f"Unknown action type: {type(action)}")

    # ------------------------------------------------------------------
    # Stop-condition checks (MASTER_PLAN §W1)
    # ------------------------------------------------------------------

    def _check_stop(self, ctx: RunContext) -> Optional[StopReason]:
        if ctx.step >= ctx.config.max_steps:
            return StopReason.MAX_STEPS
        if ctx.elapsed_ms >= ctx.config.max_wall_time_ms:
            return StopReason.MAX_WALL_TIME
        if ctx.failures >= ctx.config.max_failures:
            return StopReason.MAX_FAILURES
        if ctx.consecutive_no_ops >= NO_OP_THRESHOLD:
            return StopReason.NO_OP_LOOP
        return None

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def _finalize(
        self,
        ctx: RunContext,
        stop_reason: StopReason,
        *,
        error: Optional[str] = None,
    ) -> RunResult:
        # Extract the last assistant text if any
        response = None
        for msg in reversed(ctx.messages):
            if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                response = msg["content"]
                break

        return RunResult(
            run_id=ctx.run_id,
            success=stop_reason == StopReason.COMPLETED and error is None,
            stop_reason=stop_reason,
            response=response,
            artifacts=ctx.artifacts,
            trace=ctx.trace,
            steps=ctx.step,
            wall_time_ms=ctx.elapsed_ms,
            error=error,
        )
