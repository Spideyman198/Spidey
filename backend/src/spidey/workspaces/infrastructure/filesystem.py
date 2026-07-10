"""GuardedFileSystem — the SafeFileSystem adapter (SEC-FS).

Containment is enforced in two layers. Layer 1 is the pure
``normalize_relative_path`` policy (rejects absolute paths, drive letters, UNC,
and ``..``). Layer 2, here, resolves the candidate against the real filesystem
— following symlinks and NTFS junctions — and requires the result to stay under
the resolved workspace root. A symlink or junction that points outside the root
therefore resolves outside and is rejected, on every operation.

Residual risk (documented, deferred to the M9 sandbox): a resolve-then-open
sequence is theoretically TOCTOU-racy if an attacker can swap a path component
between the check and the open. Within this design the only writer to a
workspace is the contained sandbox, so the window is not reachable by untrusted
code; the sandbox is the authoritative isolation boundary for hostile execution.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from spidey.workspaces.domain.paths import PathPolicyError, normalize_relative_path
from spidey.workspaces.domain.ports import WorkspaceFile

if TYPE_CHECKING:
    from collections.abc import Iterator


class GuardedFileSystem:
    """A SafeFileSystem bound to one workspace root."""

    def __init__(self, root: Path) -> None:
        # The root must exist so symlink resolution is meaningful; resolve once
        # so containment comparisons use canonical, symlink-free anchors.
        self._root = root.resolve(strict=True)
        if not self._root.is_dir():
            msg = "workspace root is not a directory"
            raise PathPolicyError(msg)

    @property
    def root(self) -> str:
        return str(self._root)

    def _safe_path(self, relative_path: str) -> Path:
        relative = normalize_relative_path(relative_path)
        resolved = (self._root / Path(*relative.parts)).resolve(strict=False)
        if resolved != self._root and self._root not in resolved.parents:
            raise PathPolicyError("path escapes the workspace root")
        return resolved

    def read_bytes(self, relative_path: str) -> bytes:
        target = self._safe_path(relative_path)
        if target.is_symlink() or not target.is_file():
            raise PathPolicyError("not a regular file within the workspace")
        return target.read_bytes()

    def read_text(self, relative_path: str) -> str:
        return self.read_bytes(relative_path).decode("utf-8")

    def write_bytes(self, relative_path: str, data: bytes) -> None:
        target = self._safe_path(relative_path)
        # The parent must also be contained (it is, by construction of target),
        # and must not be a symlink escaping the root.
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise PathPolicyError("refusing to write through a symlink")
        target.write_bytes(data)

    def exists(self, relative_path: str) -> bool:
        try:
            return self._safe_path(relative_path).exists()
        except PathPolicyError:
            return False

    def is_file(self, relative_path: str) -> bool:
        try:
            target = self._safe_path(relative_path)
        except PathPolicyError:
            return False
        return target.is_file() and not target.is_symlink()

    def size(self, relative_path: str) -> int:
        target = self._safe_path(relative_path)
        if target.is_symlink() or not target.is_file():
            raise PathPolicyError("not a regular file within the workspace")
        return target.stat().st_size

    def walk_files(self) -> Iterator[WorkspaceFile]:
        # followlinks=False: never descend through a symlinked directory, which
        # could otherwise walk out of the root.
        for dirpath, dirnames, filenames in os.walk(self._root, followlinks=False):
            # Prune symlinked subdirectories from the traversal entirely.
            dirnames[:] = [d for d in dirnames if not Path(dirpath, d).is_symlink()]
            base = Path(dirpath)
            for filename in filenames:
                entry = base / filename
                if entry.is_symlink() or not entry.is_file():
                    continue
                resolved = entry.resolve(strict=False)
                if self._root not in resolved.parents:
                    continue
                rel = entry.relative_to(self._root).as_posix()
                yield WorkspaceFile(path=rel, size_bytes=entry.stat().st_size)

    def total_size(self) -> int:
        return sum(f.size_bytes for f in self.walk_files())
