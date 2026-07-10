"""Local on-disk workspace storage under the configured base directory."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from spidey.workspaces.domain.paths import PathPolicyError
from spidey.workspaces.infrastructure.filesystem import GuardedFileSystem

if TYPE_CHECKING:
    import uuid

    from spidey.platform.config import Settings


class LocalWorkspaceStorage:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.workspaces_root_path.resolve()

    def _root(self, workspace_id: uuid.UUID) -> Path:
        return self._base / str(workspace_id)

    def path_for(self, workspace_id: uuid.UUID) -> str:
        return str(self._root(workspace_id))

    async def create_root(self, workspace_id: uuid.UUID) -> str:
        root = self._root(workspace_id)
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
        return str(root)

    async def remove_root(self, workspace_id: uuid.UUID) -> None:
        root = self._root(workspace_id)
        await asyncio.to_thread(shutil.rmtree, root, ignore_errors=True)

    def filesystem(self, workspace_id: uuid.UUID) -> GuardedFileSystem:
        return GuardedFileSystem(self._root(workspace_id))

    async def copy_local_tree(self, *, workspace_id: uuid.UUID, source: str) -> None:
        source_path = Path(source)
        if not source_path.is_dir():
            raise PathPolicyError("local source is not an existing directory")
        await asyncio.to_thread(self._copy_tree_sync, source_path, self._root(workspace_id))

    @staticmethod
    def _copy_tree_sync(source: Path, destination: Path) -> None:
        # symlinks=False would COPY symlinks as-is; we want to SKIP them so a
        # link inside the source cannot import external files. ignore_dangling
        # plus an explicit ignore of symlinked entries does that.
        def _ignore(directory: str, names: list[str]) -> set[str]:
            base = Path(directory)
            return {name for name in names if (base / name).is_symlink()}

        shutil.copytree(
            source,
            destination,
            ignore=_ignore,
            dirs_exist_ok=True,
        )
