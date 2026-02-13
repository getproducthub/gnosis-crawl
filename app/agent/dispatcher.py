"""Tool dispatcher: validates, executes, and normalizes tool calls for the agent loop.

Both external (Mode A) and internal (Mode B) paths share the same ToolCall/ToolResult
primitives. The dispatcher adds timeout enforcement, retry handling, and typed error
normalization so the loop caller never sees raw exceptions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import List, Optional

from app.agent.types import ToolCall, ToolResult, RunConfig
from app.agent.errors import (
    ExecutionError,
    PolicyDeniedError,
    ToolTimeoutError,
    ToolUnavailableError,
    ValidationError,
)
from app.tools.tool_registry import ToolRegistry, ToolError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 30_000
MAX_RETRIES = 1


class Dispatcher:
    """Validates and executes tool calls against the shared ToolRegistry."""

    def __init__(self, registry: ToolRegistry, config: Optional[RunConfig] = None):
        self.registry = registry
        self.config = config or RunConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def dispatch(self, call: ToolCall) -> ToolResult:
        """Execute a single ToolCall and return a normalized ToolResult."""
        start = time.monotonic()
        try:
            self._validate(call)
            result = await self._execute_with_timeout(call)
            return result
        except PolicyDeniedError as exc:
            return self._error_result(call, exc.code, str(exc), retriable=False, start=start)
        except ToolUnavailableError as exc:
            return self._error_result(call, exc.code, str(exc), retriable=False, start=start)
        except ValidationError as exc:
            return self._error_result(call, exc.code, str(exc), retriable=False, start=start)
        except ToolTimeoutError as exc:
            return self._error_result(call, exc.code, str(exc), retriable=True, start=start)
        except Exception as exc:
            logger.error("Unhandled error dispatching tool %s: %s", call.name, exc, exc_info=True)
            return self._error_result(call, "execution_error", str(exc), retriable=False, start=start)

    async def dispatch_many(self, calls: List[ToolCall]) -> List[ToolResult]:
        """Execute multiple tool calls concurrently."""
        return list(await asyncio.gather(*(self.dispatch(c) for c in calls)))

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, call: ToolCall) -> None:
        if not call.name:
            raise ValidationError("Tool name is required")

        # Check allowlist
        if self.config.allowed_tools and call.name not in self.config.allowed_tools:
            raise PolicyDeniedError(f"Tool '{call.name}' not in allowed_tools")

        # Check registry
        try:
            self.registry.get_tool(call.name)
        except ToolError:
            raise ToolUnavailableError(f"Tool '{call.name}' not found in registry")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def _execute_with_timeout(self, call: ToolCall) -> ToolResult:
        """Run the tool with a timeout, retry once on transient failure."""
        tool_instance = self.registry.get_tool(call.name)
        timeout_s = DEFAULT_TIMEOUT_MS / 1000

        last_exc: Optional[Exception] = None
        for attempt in range(1 + MAX_RETRIES):
            start = time.monotonic()
            try:
                raw_result = await asyncio.wait_for(
                    tool_instance.execute(**call.args),
                    timeout=timeout_s,
                )
                duration = int((time.monotonic() - start) * 1000)

                if raw_result.success:
                    return ToolResult(
                        tool_call_id=call.id,
                        ok=True,
                        payload=raw_result.data,
                        duration_ms=duration,
                    )
                else:
                    return ToolResult(
                        tool_call_id=call.id,
                        ok=False,
                        error_code="execution_error",
                        error_message=raw_result.error,
                        retriable=False,
                        duration_ms=duration,
                    )

            except asyncio.TimeoutError:
                last_exc = ToolTimeoutError(
                    f"Tool '{call.name}' timed out after {DEFAULT_TIMEOUT_MS}ms"
                )
            except Exception as exc:
                last_exc = exc

            if attempt < MAX_RETRIES:
                logger.warning("Retrying tool %s (attempt %d): %s", call.name, attempt + 1, last_exc)
                await asyncio.sleep(0.25)

        # Exhausted retries
        if isinstance(last_exc, ToolTimeoutError):
            raise last_exc
        raise ExecutionError(str(last_exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _error_result(
        call: ToolCall,
        error_code: str,
        message: str,
        *,
        retriable: bool,
        start: float,
    ) -> ToolResult:
        duration = int((time.monotonic() - start) * 1000)
        return ToolResult(
            tool_call_id=call.id,
            ok=False,
            error_code=error_code,
            error_message=message,
            retriable=retriable,
            duration_ms=duration,
        )

    @staticmethod
    def args_hash(args: dict) -> str:
        """Deterministic hash of tool args for trace dedup."""
        raw = json.dumps(args, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]
