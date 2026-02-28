"""Mesh routing: scoring and target selection for tool calls.

Pure logic — no I/O. Given a tool call and the current peer table,
pick the best node to execute on based on load, locality, and affinity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.mesh.models import NodeLoad, PeerState

logger = logging.getLogger(__name__)

# Scoring constants
LOCALITY_BONUS = 0.2
AFFINITY_BONUS = 0.1


@dataclass
class RouteDecision:
    """Where to route a tool call."""
    target_node_id: str
    target_url: str
    target_name: str
    score: float
    is_local: bool
    reason: str


def compute_load_score(load: NodeLoad) -> float:
    """Score 0.0–1.0 where 1.0 = fully idle."""
    if load.max_concurrent_crawls <= 0:
        return 0.0
    active = load.active_crawls + load.active_agent_runs
    available = max(0, load.max_concurrent_crawls - active)
    return available / load.max_concurrent_crawls


def select_target(
    tool_name: str,
    self_node_id: str,
    self_load: NodeLoad,
    peers: List[PeerState],
    *,
    prefer_local: bool = True,
    customer_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[RouteDecision]:
    """Pick the best node to execute a tool call on.

    Returns None if no viable target exists (shouldn't happen if self is
    always a candidate). Returns a RouteDecision with is_local=True if
    the local node wins.
    """
    candidates: List[tuple[str, str, str, float, bool]] = []  # (id, url, name, score, is_local)

    # Score self
    self_score = compute_load_score(self_load)
    if prefer_local:
        self_score += LOCALITY_BONUS
    candidates.append((self_node_id, "", "self", self_score, True))

    # Score peers
    for peer in peers:
        if not peer.healthy:
            continue

        # Capability check: does peer have the tool?
        if peer.info.tools and tool_name not in peer.info.tools:
            continue

        if peer.load is None:
            # No load data yet — assume moderate load
            score = 0.5
        else:
            score = compute_load_score(peer.load)

        candidates.append((
            peer.info.node_id,
            peer.info.advertise_url,
            peer.info.node_name,
            score,
            False,
        ))

    if not candidates:
        return None

    # Sort by score descending
    candidates.sort(key=lambda c: c[3], reverse=True)
    best = candidates[0]

    node_id, url, name, score, is_local = best
    reason = "local preferred" if is_local else f"peer {name} scored {score:.2f}"

    return RouteDecision(
        target_node_id=node_id,
        target_url=url,
        target_name=name,
        score=score,
        is_local=is_local,
        reason=reason,
    )
