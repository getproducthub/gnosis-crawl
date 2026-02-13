"""Typed event system for agent lifecycle observability.

Events are emitted at key points during an agent run. Listeners
(TraceCollector, loggers, metrics exporters) subscribe via the
EventBus and receive typed dataclass payloads.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from app.agent.types import RunConfig, RunState, StopReason, ToolCall, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventKind(str, Enum):
    RUN_START = "run_start"
    STEP_START = "step_start"
    TOOL_DISPATCH = "tool_dispatch"
    TOOL_RESULT = "tool_result"
    POLICY_DENIED = "policy_denied"
    STEP_END = "step_end"
    RUN_END = "run_end"


@dataclass(frozen=True)
class Event:
    """Base event payload."""
    kind: EventKind
    run_id: str
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass(frozen=True)
class RunStartEvent(Event):
    kind: EventKind = field(default=EventKind.RUN_START, init=False)
    task: str = ""
    config: Optional[RunConfig] = None


@dataclass(frozen=True)
class StepStartEvent(Event):
    kind: EventKind = field(default=EventKind.STEP_START, init=False)
    step_id: int = 0
    state: RunState = RunState.PLAN


@dataclass(frozen=True)
class ToolDispatchEvent(Event):
    kind: EventKind = field(default=EventKind.TOOL_DISPATCH, init=False)
    step_id: int = 0
    tool_call: Optional[ToolCall] = None


@dataclass(frozen=True)
class ToolResultEvent(Event):
    kind: EventKind = field(default=EventKind.TOOL_RESULT, init=False)
    step_id: int = 0
    tool_result: Optional[ToolResult] = None


@dataclass(frozen=True)
class PolicyDeniedEvent(Event):
    kind: EventKind = field(default=EventKind.POLICY_DENIED, init=False)
    step_id: int = 0
    tool_name: str = ""
    reason: str = ""
    flags: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class StepEndEvent(Event):
    kind: EventKind = field(default=EventKind.STEP_END, init=False)
    step_id: int = 0
    duration_ms: int = 0


@dataclass(frozen=True)
class RunEndEvent(Event):
    kind: EventKind = field(default=EventKind.RUN_END, init=False)
    success: bool = False
    stop_reason: StopReason = StopReason.COMPLETED
    steps: int = 0
    wall_time_ms: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------

Listener = Callable[[Event], None]


class EventBus:
    """Simple synchronous pub/sub for agent events.

    Listeners are called inline — keep them fast. For async work
    (e.g. persisting to GCS), listeners should queue internally.
    """

    def __init__(self):
        self._listeners: Dict[EventKind, List[Listener]] = {}
        self._global_listeners: List[Listener] = []

    def on(self, kind: EventKind, listener: Listener) -> None:
        """Subscribe to a specific event kind."""
        self._listeners.setdefault(kind, []).append(listener)

    def on_all(self, listener: Listener) -> None:
        """Subscribe to every event kind."""
        self._global_listeners.append(listener)

    def emit(self, event: Event) -> None:
        """Dispatch an event to all matching listeners."""
        for listener in self._global_listeners:
            try:
                listener(event)
            except Exception:
                logger.exception("Global event listener error for %s", event.kind)

        for listener in self._listeners.get(event.kind, []):
            try:
                listener(event)
            except Exception:
                logger.exception("Event listener error for %s", event.kind)
