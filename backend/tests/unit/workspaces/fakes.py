"""Fakes for workspace ports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spidey.workspaces.domain.models import (
    FileManifestEntry,
    RepositorySource,
    Workspace,
    WorkspaceStatus,
)
from spidey.workspaces.domain.ports import CloneResult

if TYPE_CHECKING:
    from spidey.platform.audit import AuditAction


@dataclass
class _StoredWorkspace:
    workspace: Workspace
    encrypted_token: str | None


class FakeWorkspaceStore:
    def __init__(self) -> None:
        self.workspaces: dict[uuid.UUID, Workspace] = {}
        self.tokens: dict[uuid.UUID, str | None] = {}
        self.manifests: dict[uuid.UUID, list[FileManifestEntry]] = {}

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        name: str,
        source: RepositorySource,
        location: str,
        branch: str | None,
        encrypted_token: str | None,
    ) -> Workspace:
        now = datetime.now(tz=UTC)
        workspace = Workspace(
            id=uuid.uuid4(),
            owner_id=owner_id,
            name=name,
            source=source,
            location=location,
            branch=branch,
            status=WorkspaceStatus.PENDING,
            head_commit=None,
            size_bytes=0,
            file_count=0,
            error=None,
            created_at=now,
            updated_at=now,
        )
        self.workspaces[workspace.id] = workspace
        self.tokens[workspace.id] = encrypted_token
        return workspace

    async def get(self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace | None:
        w = self.workspaces.get(workspace_id)
        return w if w is not None and w.owner_id == owner_id else None

    async def get_with_token(self, *, workspace_id: uuid.UUID) -> _StoredWorkspace | None:
        w = self.workspaces.get(workspace_id)
        return None if w is None else _StoredWorkspace(w, self.tokens.get(workspace_id))

    async def list_for_owner(self, *, owner_id: uuid.UUID) -> list[Workspace]:
        return [w for w in self.workspaces.values() if w.owner_id == owner_id]

    async def update_status(
        self,
        *,
        workspace_id: uuid.UUID,
        status: WorkspaceStatus,
        head_commit: str | None = None,
        size_bytes: int | None = None,
        file_count: int | None = None,
        error: str | None = None,
    ) -> None:
        w = self.workspaces[workspace_id]
        self.workspaces[workspace_id] = w.model_copy(
            update={
                "status": status,
                "error": error,
                "head_commit": head_commit if head_commit is not None else w.head_commit,
                "size_bytes": size_bytes if size_bytes is not None else w.size_bytes,
                "file_count": file_count if file_count is not None else w.file_count,
            }
        )

    async def replace_manifest(
        self, *, workspace_id: uuid.UUID, entries: list[FileManifestEntry]
    ) -> None:
        self.manifests[workspace_id] = entries

    async def get_manifest(
        self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[FileManifestEntry]:
        w = self.workspaces.get(workspace_id)
        if w is None or w.owner_id != owner_id:
            return []
        return self.manifests.get(workspace_id, [])

    async def delete(self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace | None:
        w = self.workspaces.get(workspace_id)
        if w is None or w.owner_id != owner_id:
            return None
        del self.workspaces[workspace_id]
        return w


class FakeGitProvider:
    """Simulates a clone by writing a small tree into the destination."""

    def __init__(self, *, fail: bool = False, files: dict[str, bytes] | None = None) -> None:
        self.fail = fail
        self.files = files or {"README.md": b"# repo\n", "app.py": b"print(1)\n"}
        self.received_token: str | None = None
        self.received_url: str | None = None

    async def clone(
        self, *, url: str, branch: str | None, token: str | None, destination: str
    ) -> CloneResult:
        self.received_token = token
        self.received_url = url
        if self.fail:
            from spidey.workspaces.infrastructure import GitCloneError

            raise GitCloneError("repository could not be cloned")
        for rel, content in self.files.items():
            path = Path(destination) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return CloneResult(head_commit="a" * 40, branch=branch or "main")

    async def head_commit(self, path: str) -> CloneResult | None:
        return None

    async def ensure_repo(self, path: str, *, author_name: str, author_email: str) -> None: ...

    async def ensure_branch(self, path: str, branch: str) -> None: ...

    async def commit_all(self, path: str, *, message: str) -> str | None:
        return None

    async def diff(self, path: str, *, base: str | None = None) -> str:
        return ""


@dataclass
class _AuditEvent:
    action: str
    outcome: str
    details: dict[str, Any]


class FakeAuditLogger:
    def __init__(self) -> None:
        self.events: list[_AuditEvent] = []

    async def record(self, action: AuditAction, *, outcome: str, **details: Any) -> None:
        self.events.append(_AuditEvent(action.value, outcome, details))

    def actions(self) -> list[str]:
        return [e.action for e in self.events]
