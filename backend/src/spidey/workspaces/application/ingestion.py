"""Repository ingestion: clone/copy a repo into a workspace, then inventory it.

Runs in a Celery worker. Progress is expressed as durable status transitions on
the workspace record (pending → ingesting → ready | failed); the live event
stream (Redis Streams) that the UI consumes is layered on in M6 without
changing this flow. Every terminal state is audited, and any failure leaves a
safe, generic error on the record and cleans up the partial tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.platform.audit import AuditAction
from spidey.platform.errors import SpideyError
from spidey.platform.logging import get_logger
from spidey.platform.security import DecryptionError
from spidey.workspaces.application.manifest import build_manifest
from spidey.workspaces.domain.models import RepositorySource, WorkspaceStatus

if TYPE_CHECKING:
    import uuid

    from spidey.platform.audit import AuditSink
    from spidey.platform.security import SecretCipher
    from spidey.workspaces.domain.ports import GitProvider, WorkspaceStorage, WorkspaceStore

_logger = get_logger("spidey.workspaces.ingestion")


class QuotaExceededError(SpideyError):
    status = 413
    title = "Workspace quota exceeded"


class IngestionService:
    def __init__(
        self,
        *,
        store: WorkspaceStore,
        storage: WorkspaceStorage,
        git: GitProvider,
        cipher: SecretCipher,
        audit: AuditSink,
        max_workspace_bytes: int,
        max_file_bytes: int,
    ) -> None:
        self._store = store
        self._storage = storage
        self._git = git
        self._cipher = cipher
        self._audit = audit
        self._max_workspace_bytes = max_workspace_bytes
        self._max_file_bytes = max_file_bytes

    async def ingest(self, workspace_id: uuid.UUID) -> None:
        stored = await self._store.get_with_token(workspace_id=workspace_id)
        if stored is None:
            _logger.warning("ingest_unknown_workspace", workspace_id=str(workspace_id))
            return
        workspace = stored.workspace

        await self._store.update_status(workspace_id=workspace_id, status=WorkspaceStatus.INGESTING)
        try:
            head_commit = await self._acquire_tree(
                workspace_id=workspace_id,
                source=workspace.source,
                location=workspace.location,
                branch=workspace.branch,
                encrypted_token=stored.encrypted_token,
            )
            size_bytes, file_count = await self._inventory(workspace_id)
        except Exception as exc:
            await self._fail(workspace_id, owner_id=workspace.owner_id, error=exc)
            return

        await self._store.update_status(
            workspace_id=workspace_id,
            status=WorkspaceStatus.READY,
            head_commit=head_commit,
            size_bytes=size_bytes,
            file_count=file_count,
            error=None,
        )
        await self._audit.record(
            AuditAction.WORKSPACE_INGESTED,
            outcome="success",
            actor_user_id=workspace.owner_id,
            target=str(workspace_id),
            file_count=file_count,
            size_bytes=size_bytes,
        )
        _logger.info(
            "workspace_ingested",
            workspace_id=str(workspace_id),
            files=file_count,
            size_bytes=size_bytes,
        )

    async def _acquire_tree(
        self,
        *,
        workspace_id: uuid.UUID,
        source: RepositorySource,
        location: str,
        branch: str | None,
        encrypted_token: str | None,
    ) -> str | None:
        # Start from a clean root every ingest so a retry cannot mix trees.
        await self._storage.remove_root(workspace_id)
        destination = await self._storage.create_root(workspace_id)

        if source is RepositorySource.GITHUB:
            token = self._cipher.decrypt(encrypted_token) if encrypted_token else None
            result = await self._git.clone(
                url=location, branch=branch, token=token, destination=destination
            )
            return result.head_commit

        await self._storage.copy_local_tree(workspace_id=workspace_id, source=location)
        result = await self._git.head_commit(destination)
        return result.head_commit if result is not None else None

    async def _inventory(self, workspace_id: uuid.UUID) -> tuple[int, int]:
        fs = self._storage.filesystem(workspace_id)
        total = fs.total_size()
        if total > self._max_workspace_bytes:
            msg = f"ingested tree ({total} bytes) exceeds the workspace quota"
            raise QuotaExceededError(msg)
        entries = build_manifest(fs, max_file_bytes=self._max_file_bytes)
        await self._store.replace_manifest(workspace_id=workspace_id, entries=entries)
        return total, len(entries)

    async def _fail(
        self, workspace_id: uuid.UUID, *, owner_id: uuid.UUID, error: Exception
    ) -> None:
        # Surface only a safe, generic message; details go to logs/audit, never
        # to the workspace record a client can read.
        detail = error.detail if isinstance(error, SpideyError) else "ingestion failed"
        if isinstance(error, DecryptionError):
            detail = "stored credential could not be decrypted"
        await self._storage.remove_root(workspace_id)
        await self._store.update_status(
            workspace_id=workspace_id, status=WorkspaceStatus.FAILED, error=detail
        )
        await self._audit.record(
            AuditAction.WORKSPACE_INGEST_FAILED,
            outcome="failure",
            actor_user_id=owner_id,
            target=str(workspace_id),
            reason=type(error).__name__,
        )
        _logger.warning(
            "workspace_ingest_failed",
            workspace_id=str(workspace_id),
            error_type=type(error).__name__,
        )
