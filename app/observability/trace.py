"""Trace collector: accumulates step traces and persists run summaries.

The TraceCollector listens to EventBus events and builds the trace
incrementally. At run end it serializes the full trace to JSON and
persists it via CrawlStorageService (local or GCS).

Trace format is replay-friendly: load the JSON, iterate steps, and
re-execute or diff against a new run.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.agent.types import RunResult, RunState, StepTrace, StopReason
from app.observability.events import (
    Event,
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
from app.policy.redaction import redact_dict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run summary (what gets persisted)
# ---------------------------------------------------------------------------

@dataclass
class RunSummary:
    """Replay-friendly run summary — the top-level persisted object."""
    run_id: str
    task: str
    success: bool
    stop_reason: str
    steps: int
    wall_time_ms: int
    failures: int
    response: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    policy_denials: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ---------------------------------------------------------------------------
# Trace collector
# ---------------------------------------------------------------------------

class TraceCollector:
    """Accumulates trace data from EventBus events during a run.

    Usage:
        bus = EventBus()
        collector = TraceCollector(run_id="abc123", redact=True)
        collector.attach(bus)
        # ... engine emits events ...
        summary = collector.finalize(run_result)
    """

    def __init__(self, run_id: str, *, redact: bool = True):
        self.run_id = run_id
        self.redact = redact

        self._task: str = ""
        self._config_snapshot: Dict[str, Any] = {}
        self._started_at: Optional[str] = None
        self._traces: List[Dict[str, Any]] = []
        self._policy_denials: List[Dict[str, Any]] = []
        self._step_starts: Dict[int, int] = {}  # step_id -> timestamp_ms
        self._failures: int = 0

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def attach(self, bus: EventBus) -> None:
        """Subscribe to all relevant events on the bus."""
        bus.on(EventKind.RUN_START, self._on_run_start)
        bus.on(EventKind.STEP_START, self._on_step_start)
        bus.on(EventKind.TOOL_DISPATCH, self._on_tool_dispatch)
        bus.on(EventKind.TOOL_RESULT, self._on_tool_result)
        bus.on(EventKind.POLICY_DENIED, self._on_policy_denied)
        bus.on(EventKind.STEP_END, self._on_step_end)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_run_start(self, event: Event) -> None:
        e: RunStartEvent = event  # type: ignore[assignment]
        self._task = e.task
        self._started_at = datetime.now(timezone.utc).isoformat()
        if e.config:
            self._config_snapshot = {
                "max_steps": e.config.max_steps,
                "max_wall_time_ms": e.config.max_wall_time_ms,
                "max_failures": e.config.max_failures,
                "allowed_tools": e.config.allowed_tools,
                "allowed_domains": e.config.allowed_domains,
                "block_private_ranges": e.config.block_private_ranges,
                "redact_secrets": e.config.redact_secrets,
            }

    def _on_step_start(self, event: Event) -> None:
        e: StepStartEvent = event  # type: ignore[assignment]
        self._step_starts[e.step_id] = e.timestamp_ms

    def _on_tool_dispatch(self, event: Event) -> None:
        e: ToolDispatchEvent = event  # type: ignore[assignment]
        if e.tool_call is None:
            return
        entry = {
            "run_id": self.run_id,
            "step_id": e.step_id,
            "event": "tool_dispatch",
            "tool_name": e.tool_call.name,
            "args_hash": _quick_hash(e.tool_call.args),
            "timestamp_ms": e.timestamp_ms,
        }
        if self.redact:
            entry = redact_dict(entry)
        self._traces.append(entry)

    def _on_tool_result(self, event: Event) -> None:
        e: ToolResultEvent = event  # type: ignore[assignment]
        if e.tool_result is None:
            return
        r = e.tool_result
        entry = {
            "run_id": self.run_id,
            "step_id": e.step_id,
            "event": "tool_result",
            "tool_call_id": r.tool_call_id,
            "ok": r.ok,
            "error_code": r.error_code,
            "duration_ms": r.duration_ms,
            "retriable": r.retriable,
            "timestamp_ms": e.timestamp_ms,
        }
        if not r.ok:
            self._failures += 1
        self._traces.append(entry)

    def _on_policy_denied(self, event: Event) -> None:
        e: PolicyDeniedEvent = event  # type: ignore[assignment]
        denial = {
            "run_id": self.run_id,
            "step_id": e.step_id,
            "tool_name": e.tool_name,
            "reason": e.reason,
            "flags": e.flags,
            "timestamp_ms": e.timestamp_ms,
        }
        self._policy_denials.append(denial)
        self._traces.append({**denial, "event": "policy_denied"})

    def _on_step_end(self, event: Event) -> None:
        e: StepEndEvent = event  # type: ignore[assignment]
        entry = {
            "run_id": self.run_id,
            "step_id": e.step_id,
            "event": "step_end",
            "duration_ms": e.duration_ms,
            "timestamp_ms": e.timestamp_ms,
        }
        self._traces.append(entry)

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def finalize(self, result: RunResult) -> RunSummary:
        """Build a RunSummary from accumulated trace data and the RunResult."""
        return RunSummary(
            run_id=result.run_id,
            task=self._task,
            success=result.success,
            stop_reason=result.stop_reason.value,
            steps=result.steps,
            wall_time_ms=result.wall_time_ms,
            failures=self._failures,
            response=result.response,
            error=result.error,
            started_at=self._started_at,
            ended_at=datetime.now(timezone.utc).isoformat(),
            config_snapshot=self._config_snapshot,
            trace=self._traces,
            artifacts=[redact_dict(a) for a in result.artifacts] if self.redact else result.artifacts,
            policy_denials=self._policy_denials,
        )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

async def persist_trace(
    summary: RunSummary,
    session_id: str,
    user_email: Optional[str] = None,
) -> str:
    """Persist a RunSummary to storage and return the filename.

    Uses CrawlStorageService so it works in both local and GCS modes.
    Traces are stored under: {customer_hash}/{session_id}/traces/{run_id}.json
    """
    from app.storage import CrawlStorageService

    storage = CrawlStorageService(user_email=user_email)
    filename = f"traces/{summary.run_id}.json"
    await storage.save_file(summary.to_json(), filename, session_id)
    logger.info("Persisted trace %s to %s/%s", summary.run_id, session_id, filename)
    return filename


async def load_trace(
    run_id: str,
    session_id: str,
    user_email: Optional[str] = None,
) -> Optional[RunSummary]:
    """Load a persisted RunSummary from storage."""
    from app.storage import CrawlStorageService

    storage = CrawlStorageService(user_email=user_email)
    filename = f"traces/{run_id}.json"
    try:
        data = await storage.get_file(filename, session_id)
        d = json.loads(data.decode("utf-8"))
        return RunSummary(**d)
    except FileNotFoundError:
        return None
    except Exception:
        logger.exception("Failed to load trace %s", run_id)
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _quick_hash(args: dict) -> str:
    """Fast deterministic hash for trace dedup (not crypto-grade)."""
    import hashlib
    raw = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]
