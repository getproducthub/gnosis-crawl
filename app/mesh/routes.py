"""FastAPI routes for mesh protocol endpoints.

POST /mesh/join       — peer discovery
POST /mesh/heartbeat  — load reporting
POST /mesh/execute    — remote tool execution
POST /mesh/leave      — graceful departure
GET  /mesh/peers      — list known peers
GET  /mesh/status     — this node's mesh status
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request

from app.mesh.models import (
    HeartbeatRequest,
    HeartbeatResponse,
    JoinRequest,
    JoinResponse,
    LeaveRequest,
    LeaveResponse,
    MeshToolRequest,
    MeshToolResponse,
    MeshToolResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mesh", tags=["mesh"])


def _get_coordinator(request: Request):
    """Extract the MeshCoordinator from app state."""
    coordinator = getattr(request.app.state, "mesh_coordinator", None)
    if coordinator is None:
        raise HTTPException(status_code=503, detail="Mesh not enabled")
    return coordinator


def _verify_or_401(request: Request, token: str):
    """Verify mesh token or raise 401."""
    coordinator = _get_coordinator(request)
    if not coordinator.verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid mesh token")


# ---------------------------------------------------------------------------
# POST /mesh/join
# ---------------------------------------------------------------------------

@router.post("/join", response_model=JoinResponse)
async def mesh_join(body: JoinRequest, request: Request):
    """Handle a peer joining the mesh."""
    _verify_or_401(request, body.mesh_token)
    coordinator = _get_coordinator(request)

    # Register the joining peer
    coordinator.register_peer(body.node_info)
    logger.info("Peer joined: %s (%s)", body.node_info.node_name, body.node_info.node_id)

    return JoinResponse(
        ok=True,
        node_info=coordinator.node_info,
        known_peers=coordinator.get_known_peer_infos(),
    )


# ---------------------------------------------------------------------------
# POST /mesh/heartbeat
# ---------------------------------------------------------------------------

@router.post("/heartbeat", response_model=HeartbeatResponse)
async def mesh_heartbeat(body: HeartbeatRequest, request: Request):
    """Receive a heartbeat from a peer."""
    _verify_or_401(request, body.mesh_token)
    coordinator = _get_coordinator(request)

    coordinator.update_peer_load(body.node_load.node_id, body.node_load)

    return HeartbeatResponse(ok=True)


# ---------------------------------------------------------------------------
# POST /mesh/execute
# ---------------------------------------------------------------------------

@router.post("/execute", response_model=MeshToolResponse)
async def mesh_execute(body: MeshToolRequest, request: Request):
    """Execute a tool call forwarded from a peer."""
    _verify_or_401(request, body.mesh_token)
    coordinator = _get_coordinator(request)

    # 1-hop enforcement: refuse if this is already a forwarded call
    if body.hop_count > 0:
        return MeshToolResponse(
            ok=False,
            error="Max hop count exceeded — refusing to forward",
        )

    # Execute the tool locally via the tool registry
    from app.tools.tool_registry import get_global_registry, ToolError

    registry = get_global_registry()
    tool_call = body.tool_call

    try:
        tool_instance = registry.get_tool(tool_call.name)
    except ToolError:
        return MeshToolResponse(
            ok=False,
            error=f"Tool '{tool_call.name}' not found on this node",
        )

    start = time.monotonic()
    try:
        result = await tool_instance.execute(**tool_call.args)
        duration = int((time.monotonic() - start) * 1000)

        if result.success:
            return MeshToolResponse(
                ok=True,
                tool_result=MeshToolResult(
                    tool_call_id=tool_call.id,
                    ok=True,
                    payload=result.data,
                    duration_ms=duration,
                ),
                executed_on=coordinator.node_id,
            )
        else:
            return MeshToolResponse(
                ok=True,
                tool_result=MeshToolResult(
                    tool_call_id=tool_call.id,
                    ok=False,
                    error_code="execution_error",
                    error_message=result.error,
                    duration_ms=duration,
                ),
                executed_on=coordinator.node_id,
            )
    except Exception as exc:
        duration = int((time.monotonic() - start) * 1000)
        logger.error("Mesh tool execution failed: %s", exc, exc_info=True)
        return MeshToolResponse(
            ok=True,
            tool_result=MeshToolResult(
                tool_call_id=tool_call.id,
                ok=False,
                error_code="execution_error",
                error_message=str(exc),
                duration_ms=duration,
            ),
            executed_on=coordinator.node_id,
        )


# ---------------------------------------------------------------------------
# POST /mesh/leave
# ---------------------------------------------------------------------------

@router.post("/leave", response_model=LeaveResponse)
async def mesh_leave(body: LeaveRequest, request: Request):
    """Handle a peer leaving the mesh."""
    _verify_or_401(request, body.mesh_token)
    coordinator = _get_coordinator(request)

    coordinator.remove_peer(body.node_id)
    logger.info("Peer left: %s", body.node_id)

    return LeaveResponse(ok=True)


# ---------------------------------------------------------------------------
# GET /mesh/peers
# ---------------------------------------------------------------------------

@router.get("/peers")
async def mesh_peers(request: Request) -> Dict[str, Any]:
    """List all known mesh peers."""
    coordinator = _get_coordinator(request)
    peers = coordinator.get_peers()
    return {
        "node_id": coordinator.node_id,
        "node_name": coordinator.node_name,
        "peer_count": len(peers),
        "peers": [
            {
                "node_id": p.info.node_id,
                "node_name": p.info.node_name,
                "advertise_url": p.info.advertise_url,
                "tools": p.info.tools,
                "capabilities": p.info.capabilities,
                "healthy": p.healthy,
                "missed_heartbeats": p.missed_heartbeats,
                "last_heartbeat_ms": p.last_heartbeat_ms,
                "load": p.load.model_dump() if p.load else None,
            }
            for p in peers
        ],
    }


# ---------------------------------------------------------------------------
# GET /mesh/status
# ---------------------------------------------------------------------------

@router.get("/status")
async def mesh_status(request: Request) -> Dict[str, Any]:
    """This node's mesh status."""
    coordinator = _get_coordinator(request)
    load = coordinator.get_self_load()
    healthy_peers = coordinator.get_healthy_peers()
    return {
        "node_id": coordinator.node_id,
        "node_name": coordinator.node_name,
        "advertise_url": coordinator.advertise_url,
        "tools": coordinator.node_info.tools,
        "capabilities": coordinator.node_info.capabilities,
        "load": load.model_dump(),
        "total_peers": len(coordinator.get_peers()),
        "healthy_peers": len(healthy_peers),
    }
