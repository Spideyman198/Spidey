"""Workspaces ports."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterator

    from spidey.workspaces.domain.models import (
        FileManifestEntry,
        RepositorySource,
        Workspace,
        WorkspaceStatus,
    )


class WorkspaceFile(BaseModel):
    """A file surfaced by a guarded directory walk."""

    model_config = ConfigDict(frozen=True)

    path: str  # workspace-relative, forward-slashed
    size_bytes: int


class SafeFileSystem(Protocol):
    """Guarded access to one workspace's tree (SEC-FS).

    Every method takes a workspace-relative path and guarantees the resolved
    target stays within the workspace root — traversal, absolute paths,
    symlinks, and junctions that escape the root all raise ``PathPolicyError``.
    There is deliberately no method that accepts an absolute path.
    """

    @property
    def root(self) -> str: ...

    def read_bytes(self, relative_path: str) -> bytes: ...
    def read_text(self, relative_path: str) -> str: ...
    def write_bytes(self, relative_path: str, data: bytes) -> None: ...
    def exists(self, relative_path: str) -> bool: ...
    def is_file(self, relative_path: str) -> bool: ...
    def size(self, relative_path: str) -> int: ...

    def walk_files(self) -> Iterator[WorkspaceFile]:
        """Yield every regular file under the root, skipping symlinks and any
        entry that would escape containment."""
        ...

    def total_size(self) -> int:
        """Sum of contained regular-file sizes (for quota enforcement)."""
        ...


class CloneResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    head_commit: str
    branch: str


class GitProvider(Protocol):
    """Clones a remote repository and manages the local run-branch workflow.

    Clone implementations must validate the URL against the SSRF allow-list
    before any network activity, and must never let a token appear in an error
    message or log line. The local operations (M8) never touch the network —
    branch-per-run isolation and commits are strictly workspace-local; pushing
    is a later, separately-gated milestone.
    """

    async def clone(
        self,
        *,
        url: str,
        branch: str | None,
        token: str | None,
        destination: str,
    ) -> CloneResult: ...

    async def head_commit(self, path: str) -> CloneResult | None:
        """Read HEAD of a git repo at ``path``, or None if it is not one."""
        ...

    async def ensure_repo(self, path: str, *, author_name: str, author_email: str) -> None:
        """Open the repo at ``path``, initializing one if absent, and set the
        local commit identity (never the user's global config)."""
        ...

    async def ensure_branch(self, path: str, branch: str) -> None:
        """Create the branch if missing and check it out (idempotent)."""
        ...

    async def commit_all(self, path: str, *, message: str) -> str | None:
        """Stage every change and commit atomically. Returns the new commit sha,
        or None when the tree is clean (an empty commit is never created)."""
        ...

    async def diff(self, path: str, *, base: str | None = None) -> str:
        """Unified diff of the working tree (including new files) against
        ``base`` (a ref/sha), defaulting to HEAD."""
        ...


class WorkspaceStorage(Protocol):
    """Owns the on-disk workspace area under the configured base directory.

    All returned filesystem handles are containment-guarded; ``copy_local_tree``
    is the only path that reads outside the base directory (local ingestion),
    and it skips symlinks so a source tree cannot drag in external files.
    """

    async def create_root(self, workspace_id: uuid.UUID) -> str:
        """Create an empty root for the workspace and return its absolute path."""
        ...

    async def remove_root(self, workspace_id: uuid.UUID) -> None: ...

    def path_for(self, workspace_id: uuid.UUID) -> str: ...

    def filesystem(self, workspace_id: uuid.UUID) -> SafeFileSystem: ...

    async def copy_local_tree(self, *, workspace_id: uuid.UUID, source: str) -> None:
        """Copy a local directory tree into the workspace root (symlink-skip).
        Raises ``PathPolicyError`` if the source is missing or not a directory."""
        ...


class StoredWorkspace(Protocol):
    @property
    def workspace(self) -> Workspace: ...
    @property
    def encrypted_token(self) -> str | None: ...


class WorkspaceStore(Protocol):
    """Persistence for workspaces, their repository metadata (including the
    envelope-encrypted access token), and file manifests."""

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        source: RepositorySource,
        location: str,
        branch: str | None,
        encrypted_token: str | None,
    ) -> Workspace: ...

    async def get(self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace | None: ...

    async def get_with_token(self, *, workspace_id: uuid.UUID) -> StoredWorkspace | None:
        """Unscoped lookup for the ingestion worker; not exposed to API callers."""
        ...

    async def list_for_owner(self, *, owner_id: uuid.UUID) -> list[Workspace]: ...

    async def update_status(
        self,
        *,
        workspace_id: uuid.UUID,
        status: WorkspaceStatus,
        head_commit: str | None = None,
        size_bytes: int | None = None,
        file_count: int | None = None,
        error: str | None = None,
    ) -> None: ...

    async def replace_manifest(
        self, *, workspace_id: uuid.UUID, entries: list[FileManifestEntry]
    ) -> None: ...

    async def get_manifest(
        self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[FileManifestEntry]: ...

    async def delete(self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace | None:
        """Delete and return the removed workspace (for root cleanup), or None."""
        ...
