"""Mesh coordinator — agents talking to agents.

Every gnosis-crawl instance is a peer. Enable with MESH_ENABLED=true.
"""

from app.mesh.coordinator import MeshCoordinator
from app.mesh.dispatcher import MeshDispatcher

__all__ = ["MeshCoordinator", "MeshDispatcher"]
