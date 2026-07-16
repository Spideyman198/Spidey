"""Code-indexing task (queue: ingestion).

Runs after a successful ingestion (chained by the ingestion task) or on demand.
Reads the workspace's indexable file manifest and source through the guarded
filesystem, then delegates the incremental index to codeintel.
"""

from __future__ import annotations

import asyncio
import uuid

from celery import shared_task

from spidey.codeintel.application import EmbeddingPipeline, IndexService
from spidey.codeintel.domain.models import ManifestEntry
from spidey.codeintel.infrastructure import PostgresGraphStore, PostgresSymbolStore
from spidey.platform.logging import get_logger
from spidey.workers.adapters import WorkspaceSourceReader
from spidey.workers.container import get_worker_container
from spidey.workspaces.domain.models import WorkspaceStatus
from spidey.workspaces.infrastructure import PostgresWorkspaceStore

_logger = get_logger("spidey.workers.indexing")


@shared_task(name="spidey.codeintel.index", max_retries=0, acks_late=True)
def index_workspace(workspace_id: str) -> None:
    asyncio.run(_index(uuid.UUID(workspace_id)))


async def _index(workspace_id: uuid.UUID) -> None:
    container = get_worker_container()

    async with container.session_factory() as session:
        ws_store = PostgresWorkspaceStore(session)
        stored = await ws_store.get_with_token(workspace_id=workspace_id)
        if stored is None or stored.workspace.status is not WorkspaceStatus.READY:
            _logger.info("index_skipped_not_ready", workspace_id=str(workspace_id))
            return
        entries = await ws_store.get_manifest(
            owner_id=stored.workspace.owner_id, workspace_id=workspace_id
        )

    manifest = [ManifestEntry(path=e.path, sha256=e.sha256) for e in entries if e.indexable]
    reader = WorkspaceSourceReader(container.workspace_storage.filesystem(workspace_id))

    async with container.session_factory() as session:
        service = IndexService(
            store=PostgresSymbolStore(session),
            parser=container.code_parser,
            embedding=EmbeddingPipeline(
                dense=container.dense_embedder,
                sparse=container.sparse_embedder,
                vectors=container.vector_index,
            ),
            graph=PostgresGraphStore(session),
        )
        outcome = await service.reindex(workspace_id=workspace_id, manifest=manifest, reader=reader)
        await session.commit()

    _logger.info(
        "workspace_indexed",
        workspace_id=str(workspace_id),
        symbols=outcome.symbol_count,
        chunks=outcome.chunk_count,
        files=outcome.files_indexed,
    )
