"""Pydantic models for mesh peer communication.

NodeInfo describes a peer's identity and capabilities.
NodeLoad carries real-time load metrics for routing decisions.
MeshToolRequest/Response wrap tool calls crossing the wire.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Peer identity
# ---------------------------------------------------------------------------

class NodeInfo(BaseModel):
    """Identity and capabilities of a mesh peer."""
    node_id: str
    node_name: str
    advertise_url: str
    tools: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    version: str = "1.0.0"
    joined_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000))


class NodeLoad(BaseModel):
    """Real-time load snapshot sent with heartbeats."""
    node_id: str
    active_crawls: int = 0
    active_agent_runs: int = 0
    browser_pool_free: int = 0
    max_concurrent_crawls: int = 5
    timestamp_ms: int = Field(default_factory=lambda: int(time.time() * 1000))


# ---------------------------------------------------------------------------
# Peer state (coordinator-internal, not sent over wire as-is)
# ---------------------------------------------------------------------------

class PeerState(BaseModel):
    """Internal tracking of a known peer."""
    info: NodeInfo
    load: Optional[NodeLoad] = None
    last_heartbeat_ms: int = Field(default_factory=lambda: int(time.time() * 1000))
    missed_heartbeats: int = 0
    healthy: bool = True


# ---------------------------------------------------------------------------
# Wire protocol: join
# ---------------------------------------------------------------------------

class JoinRequest(BaseModel):
    """POST /mesh/join body."""
    node_info: NodeInfo
    mesh_token: str


class JoinResponse(BaseModel):
    """Response to a join request."""
    ok: bool
    node_info: NodeInfo  # responder's own info
    known_peers: List[NodeInfo] = Field(default_factory=list)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Wire protocol: heartbeat
# ---------------------------------------------------------------------------

class HeartbeatRequest(BaseModel):
    """POST /mesh/heartbeat body."""
    node_load: NodeLoad
    mesh_token: str


class HeartbeatResponse(BaseModel):
    """Ack for heartbeat."""
    ok: bool
    timestamp_ms: int = Field(default_factory=lambda: int(time.time() * 1000))


# ---------------------------------------------------------------------------
# Wire protocol: tool execution
# ---------------------------------------------------------------------------

class MeshToolCall(BaseModel):
    """A tool call to be executed on a remote peer."""
    id: str
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)


class MeshContext(BaseModel):
    """Execution context forwarded with remote tool calls."""
    run_id: Optional[str] = None
    customer_id: Optional[str] = None
    session_id: Optional[str] = None
    originating_node: Optional[str] = None


class MeshToolRequest(BaseModel):
    """POST /mesh/execute body."""
    tool_call: MeshToolCall
    context: MeshContext = Field(default_factory=MeshContext)
    mesh_token: str
    hop_count: int = 0  # 1-hop max enforcement


class MeshToolResult(BaseModel):
    """Result of a remote tool execution."""
    tool_call_id: str
    ok: bool
    payload: Any = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: int = 0


class MeshToolResponse(BaseModel):
    """Response to POST /mesh/execute."""
    ok: bool
    tool_result: Optional[MeshToolResult] = None
    executed_on: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Wire protocol: leave
# ---------------------------------------------------------------------------

class LeaveRequest(BaseModel):
    """POST /mesh/leave body."""
    node_id: str
    mesh_token: str


class LeaveResponse(BaseModel):
    """Ack for leave."""
    ok: bool
