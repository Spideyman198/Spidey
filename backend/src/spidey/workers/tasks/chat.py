"""Scripted-chat task (M6 exit slice).

Assembles the gateway (with metering, capture, cache, budget), the tool registry
(native code search), and the ChatRunner from the process container, runs one
user turn, and commits — the outbox events it produced are then relayed to the
run's SSE stream by the event pump.
"""

from __future__ import annotations

import asyncio
import uuid

from celery import shared_task

from spidey.agents.application import ChatRunner, ToolRegistry
from spidey.agents.infrastructure import CodeSearchProvider
from spidey.identity.domain.models import Role
from spidey.llm.application import Gateway
from spidey.llm.infrastructure import PostgresInteractionCapture
from spidey.platform.events import OutboxWriter
from spidey.platform.logging import get_logger
from spidey.workers.container import get_worker_container

_logger = get_logger("spidey.workers.chat")


@shared_task(name="spidey.agents.chat", max_retries=0, acks_late=True)
def run_chat(
    run_id: str,
    actor_user_id: str,
    user_role: str,
    message: str,
    session_id: str,
    workspace_id: str,
) -> None:
    # Positional string args to match the TaskQueue port; "" encodes an absent id.
    asyncio.run(
        _run(
            run_id=uuid.UUID(run_id),
            actor_user_id=uuid.UUID(actor_user_id),
            user_role=Role(user_role),
            message=message,
            session_id=uuid.UUID(session_id) if session_id else None,
            workspace_id=uuid.UUID(workspace_id) if workspace_id else None,
        )
    )


async def _run(
    *,
    run_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    user_role: Role,
    message: str,
    session_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None,
) -> None:
    container = get_worker_container()
    async with container.session_factory() as session:
        events = OutboxWriter(session)
        gateway = Gateway(
            registry=container.llm_registry,
            events=events,
            capture=PostgresInteractionCapture(session),
            cache=container.response_cache,
            budget=container.budget_ledger,
            max_retries=container.settings.llm_max_retries,
        )
        registry = ToolRegistry(
            providers=[
                CodeSearchProvider(
                    session_factory=container.session_factory,
                    dense_embedder=container.dense_embedder,
                    sparse_embedder=container.sparse_embedder,
                    vector_index=container.vector_index,
                )
            ],
            events=events,
        )
        runner = ChatRunner(
            gateway=gateway,
            registry=registry,
            events=events,
            stream_bus=container.stream_bus,
        )
        await runner.run(
            run_id=run_id,
            session_id=session_id,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            user_role=user_role,
            message=message,
        )
        await session.commit()
    _logger.info("chat_task_done", run_id=str(run_id))
