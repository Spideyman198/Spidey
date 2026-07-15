"""Cross-context adapters wired in the worker (interface layer).

The worker is allowed to depend on multiple contexts, so it is the correct
place to bridge one context's port to another's adapter — here, satisfying
codeintel's ``SourceReader`` with the workspaces ``SafeFileSystem``. This keeps
codeintel and workspaces independent of each other (their contexts never
import one another).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spidey.workspaces.domain.ports import SafeFileSystem


class WorkspaceSourceReader:
    """Adapts a workspace SafeFileSystem to codeintel's SourceReader port, so
    every read stays containment-guarded (SEC-FS)."""

    def __init__(self, filesystem: SafeFileSystem) -> None:
        self._fs = filesystem

    def read_bytes(self, path: str) -> bytes:
        return self._fs.read_bytes(path)
