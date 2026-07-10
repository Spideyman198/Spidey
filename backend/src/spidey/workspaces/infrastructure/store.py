"""Postgres adapter for the workspace store."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from spidey.platform.db import affected_rows
from spidey.workspaces.domain.models import (
    FileManifestEntry,
    RepositorySource,
    Workspace,
    WorkspaceStatus,
)
from spidey.workspaces.infrastructure.orm import FileManifestRecord, WorkspaceRecord

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


def _to_workspace(record: WorkspaceRecord) -> Workspace:
    return Workspace(
        id=record.id,
        owner_id=record.owner_id,
        name=record.name,
        source=RepositorySource(record.source),
        location=record.location,
        branch=record.branch,
        status=WorkspaceStatus(record.status),
        head_commit=record.head_commit,
        size_bytes=record.size_bytes,
        file_count=record.file_count,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@dataclass(frozen=True)
class _StoredWorkspace:
    workspace: Workspace
    encrypted_token: str | None


class PostgresWorkspaceStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        record = WorkspaceRecord(
            owner_id=owner_id,
            name=name,
            source=source.value,
            location=location,
            branch=branch,
            status=WorkspaceStatus.PENDING.value,
            encrypted_token=encrypted_token,
        )
        self._session.add(record)
        await self._session.flush()
        return _to_workspace(record)

    async def get(self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace | None:
        record = await self._session.scalar(
            select(WorkspaceRecord).where(
                WorkspaceRecord.id == workspace_id, WorkspaceRecord.owner_id == owner_id
            )
        )
        return None if record is None else _to_workspace(record)

    async def get_with_token(self, *, workspace_id: uuid.UUID) -> _StoredWorkspace | None:
        record = await self._session.get(WorkspaceRecord, workspace_id)
        if record is None:
            return None
        return _StoredWorkspace(_to_workspace(record), record.encrypted_token)

    async def list_for_owner(self, *, owner_id: uuid.UUID) -> list[Workspace]:
        records = await self._session.scalars(
            select(WorkspaceRecord)
            .where(WorkspaceRecord.owner_id == owner_id)
            .order_by(WorkspaceRecord.created_at.desc())
        )
        return [_to_workspace(record) for record in records]

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
        record = await self._session.get(WorkspaceRecord, workspace_id)
        if record is None:
            return
        record.status = status.value
        record.error = error
        if head_commit is not None:
            record.head_commit = head_commit
        if size_bytes is not None:
            record.size_bytes = size_bytes
        if file_count is not None:
            record.file_count = file_count
        await self._session.flush()

    async def replace_manifest(
        self, *, workspace_id: uuid.UUID, entries: list[FileManifestEntry]
    ) -> None:
        await self._session.execute(
            delete(FileManifestRecord).where(FileManifestRecord.workspace_id == workspace_id)
        )
        self._session.add_all(
            FileManifestRecord(
                workspace_id=workspace_id,
                path=entry.path,
                sha256=entry.sha256,
                size_bytes=entry.size_bytes,
                is_binary=entry.is_binary,
                indexable=entry.indexable,
            )
            for entry in entries
        )
        await self._session.flush()

    async def get_manifest(
        self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[FileManifestEntry]:
        # Join through the owning workspace so the manifest is owner-scoped.
        records = await self._session.scalars(
            select(FileManifestRecord)
            .join(WorkspaceRecord, WorkspaceRecord.id == FileManifestRecord.workspace_id)
            .where(
                WorkspaceRecord.id == workspace_id,
                WorkspaceRecord.owner_id == owner_id,
            )
            .order_by(FileManifestRecord.path)
        )
        return [
            FileManifestEntry(
                path=r.path,
                sha256=r.sha256,
                size_bytes=r.size_bytes,
                is_binary=r.is_binary,
                indexable=r.indexable,
            )
            for r in records
        ]

    async def delete(self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace | None:
        record = await self._session.scalar(
            select(WorkspaceRecord).where(
                WorkspaceRecord.id == workspace_id, WorkspaceRecord.owner_id == owner_id
            )
        )
        if record is None:
            return None
        workspace = _to_workspace(record)
        result = await self._session.execute(
            delete(WorkspaceRecord).where(WorkspaceRecord.id == workspace_id)
        )
        return workspace if affected_rows(result) else None
