"""Repository-ingestion task (queue: ingestion).

Bridges Celery's synchronous execution to the async ingestion service via a
fresh event loop per task. The service owns all status transitions and cleanup,
so the task body is deliberately thin.
"""

from __future__ import annotations

import asyncio
import uuid

from celery import shared_task

from spidey.platform.audit import AuditLogger
from spidey.workers.container import get_worker_container
from spidey.workspaces.application import IngestionService
from spidey.workspaces.infrastructure import GitPythonProvider, PostgresWorkspaceStore


@shared_task(
    name="spidey.workspaces.ingest",
    bind=False,
    max_retries=0,  # the service handles failure terminally; no blind retries
    acks_late=True,
)
def ingest_repository(workspace_id: str) -> None:
    asyncio.run(_ingest(uuid.UUID(workspace_id)))


async def _ingest(workspace_id: uuid.UUID) -> None:
    container = get_worker_container()
    async with container.session_factory() as session:
        service = IngestionService(
            store=PostgresWorkspaceStore(session),
            storage=container.workspace_storage,
            git=GitPythonProvider(container.settings),
            cipher=container.cipher,
            audit=AuditLogger(session),
            max_workspace_bytes=container.settings.workspace_max_bytes,
            max_file_bytes=container.settings.ingest_max_file_bytes,
        )
        await service.ingest(workspace_id)
        await session.commit()
