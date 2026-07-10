"""Workspace lifecycle use cases (create, list, get, delete)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.platform.audit import AuditAction
from spidey.platform.errors import NotFoundError
from spidey.workspaces.domain.models import RepositorySource, Workspace

if TYPE_CHECKING:
    import uuid

    from spidey.platform.audit import AuditSink
    from spidey.platform.security import SecretCipher
    from spidey.workspaces.domain.models import FileManifestEntry, IngestionRequest
    from spidey.workspaces.domain.ports import WorkspaceStorage, WorkspaceStore

_MISSING = "workspace does not exist"


class WorkspaceService:
    def __init__(
        self,
        *,
        store: WorkspaceStore,
        storage: WorkspaceStorage,
        cipher: SecretCipher,
        audit: AuditSink,
    ) -> None:
        self._store = store
        self._storage = storage
        self._cipher = cipher
        self._audit = audit

    async def create(
        self, *, owner_id: uuid.UUID, request: IngestionRequest, request_id: str | None
    ) -> Workspace:
        """Register a workspace in PENDING state. Ingestion runs asynchronously.

        A GitHub token, if supplied, is envelope-encrypted before it ever
        touches the database; the plaintext is discarded with this call frame.
        """
        encrypted = (
            self._cipher.encrypt(request.token)
            if request.token and request.source is RepositorySource.GITHUB
            else None
        )
        workspace = await self._store.create(
            owner_id=owner_id,
            name=request.name,
            source=request.source,
            location=request.location,
            branch=request.branch,
            encrypted_token=encrypted,
        )
        await self._audit.record(
            AuditAction.WORKSPACE_CREATED,
            outcome="success",
            actor_user_id=owner_id,
            target=str(workspace.id),
            request_id=request_id,
            source=request.source.value,
        )
        return workspace

    async def get(self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID) -> Workspace:
        workspace = await self._store.get(owner_id=owner_id, workspace_id=workspace_id)
        if workspace is None:
            raise NotFoundError(_MISSING)
        return workspace

    async def list(self, *, owner_id: uuid.UUID) -> list[Workspace]:
        return await self._store.list_for_owner(owner_id=owner_id)

    async def manifest(
        self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[FileManifestEntry]:
        await self.get(owner_id=owner_id, workspace_id=workspace_id)  # ownership check
        return await self._store.get_manifest(owner_id=owner_id, workspace_id=workspace_id)

    async def delete(
        self, *, owner_id: uuid.UUID, workspace_id: uuid.UUID, request_id: str | None
    ) -> None:
        removed = await self._store.delete(owner_id=owner_id, workspace_id=workspace_id)
        if removed is None:
            raise NotFoundError(_MISSING)
        # Remove the on-disk tree after the row is gone; a leftover directory is
        # reclaimable, a dangling DB row is not.
        await self._storage.remove_root(workspace_id)
        await self._audit.record(
            AuditAction.WORKSPACE_DELETED,
            outcome="success",
            actor_user_id=owner_id,
            target=str(workspace_id),
            request_id=request_id,
        )
