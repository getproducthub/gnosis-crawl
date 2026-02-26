"""MeshDispatcher: wraps local Dispatcher to route tool calls across nodes.

When mesh is enabled, MeshDispatcher sits between the AgentEngine and the
local Dispatcher. For each tool call, it consults the router to decide
whether to execute locally or forward to a peer. If the remote call fails,
it falls back to local execution.

When mesh is disabled, this module is never imported — zero overhead.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from app.agent.types import ToolCall, ToolResult
from app.agent.dispatcher import Dispatcher
from app.mesh.coordinator import MeshCoordinator
from app.mesh.models import MeshContext, MeshToolCall
from app.mesh.router import select_target

logger = logging.getLogger(__name__)


class MeshDispatcher:
    """Transparently routes tool calls across mesh nodes.

    Composes a local Dispatcher — all validation and execution logic
    stays in the original code. MeshDispatcher only adds the routing
    decision layer on top.
    """

    def __init__(
        self,
        local_dispatcher: Dispatcher,
        coordinator: MeshCoordinator,
        *,
        prefer_local: bool = True,
        customer_id: Optional[str] = None,
        session_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ):
        self.local = local_dispatcher
        self.coordinator = coordinator
        self.prefer_local = prefer_local
        self.customer_id = customer_id
        self.session_id = session_id
        self.run_id = run_id

    # ------------------------------------------------------------------
    # Public API (same interface as Dispatcher)
    # ------------------------------------------------------------------

    async def dispatch(self, call: ToolCall) -> ToolResult:
        """Route a tool call to the best node, falling back to local."""
        decision = select_target(
            tool_name=call.name,
            self_node_id=self.coordinator.node_id,
            self_load=self.coordinator.get_self_load(),
            peers=self.coordinator.get_healthy_peers(),
            prefer_local=self.prefer_local,
            customer_id=self.customer_id,
            session_id=self.session_id,
        )

        # No peers or local wins — execute locally
        if decision is None or decision.is_local:
            return await self.local.dispatch(call)

        # Try remote execution
        logger.info(
            "Routing tool %s to peer %s (%s) — score=%.2f reason=%s",
            call.name, decision.target_name, decision.target_node_id,
            decision.score, decision.reason,
        )

        remote_result = await self._execute_remote(call, decision.target_url)
        if remote_result is not None:
            return remote_result

        # Fallback to local on remote failure
        logger.warning(
            "Remote execution failed for %s on %s — falling back to local",
            call.name, decision.target_name,
        )
        return await self.local.dispatch(call)

    async def dispatch_many(self, calls: List[ToolCall]) -> List[ToolResult]:
        """Execute multiple tool calls, routing each independently."""
        import asyncio
        return list(await asyncio.gather(*(self.dispatch(c) for c in calls)))

    # ------------------------------------------------------------------
    # Remote execution
    # ------------------------------------------------------------------

    async def _execute_remote(self, call: ToolCall, peer_url: str) -> Optional[ToolResult]:
        """Execute a tool call on a remote peer. Returns None on failure."""
        mesh_call = MeshToolCall(id=call.id, name=call.name, args=call.args)
        context = MeshContext(
            run_id=self.run_id,
            customer_id=self.customer_id,
            session_id=self.session_id,
            originating_node=self.coordinator.node_id,
        )

        start = time.monotonic()
        response = await self.coordinator.client.execute_tool(
            peer_url, mesh_call, context,
        )

        if response is None:
            return None

        if not response.ok:
            logger.warning("Remote execute returned error: %s", response.error)
            return None

        result = response.tool_result
        if result is None:
            return None

        duration = result.duration_ms or int((time.monotonic() - start) * 1000)

        return ToolResult(
            tool_call_id=result.tool_call_id,
            ok=result.ok,
            payload=result.payload,
            error_code=result.error_code,
            error_message=result.error_message,
            duration_ms=duration,
        )
