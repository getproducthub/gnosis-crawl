"""Mesh coordinator — agents talking to agents.

Every Grub Crawler instance is a peer. Enable with MESH_ENABLED=true.
"""

from app.mesh.coordinator import MeshCoordinator
from app.mesh.dispatcher import MeshDispatcher

__all__ = ["MeshCoordinator", "MeshDispatcher"]
