"""Agent-run task (M7/M8): drive one run's LangGraph to its next pause or end.

Contract: this is the *only* place the run graph executes. It builds the graph
with a durable Postgres checkpointer keyed by ``thread_id = run_id``, then either
starts a fresh run (``PENDING``) or resumes a paused one (a human approved a plan
or an approval). The graph runs until it hits an interrupt (persisted by the
checkpointer) or reaches a terminal state; our own writes — plan, status changes,
outbox events — commit on the SQLAlchemy session at the end. A crash mid-run is
recorded as ``FAILED`` in a fresh session so the run never sticks in ``RUNNING``.
"""

from __future__ import annotations

import asyncio
import uuid

from celery import shared_task
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from spidey.agents.application import MemoryDistiller, ToolRegistry
from spidey.agents.domain.runs import RunStatus, is_terminal
from spidey.agents.graph import GraphNodes, build_run_graph, initial_state
from spidey.agents.infrastructure import (
    CodeEditProvider,
    CodeSearchProvider,
    SandboxToolProvider,
)
from spidey.agents.infrastructure.run_store import PostgresRunStore
from spidey.llm.application import Gateway
from spidey.llm.infrastructure import PostgresInteractionCapture
from spidey.memory.application import MemoryService
from spidey.memory.infrastructure import PostgresMemoryStore
from spidey.platform.audit import AuditLogger
from spidey.platform.events import EventEnvelope, OutboxWriter, RunStatusChanged
from spidey.platform.logging import get_logger
from spidey.workers.container import get_worker_container
from spidey.workspaces.application import GitWorkflowService, PrService
from spidey.workspaces.infrastructure import PostgresWorkspaceStore

_logger = get_logger("spidey.workers.agent_run")


@shared_task(name="spidey.agents.run", max_retries=0, acks_late=True)
def run_agent(run_id: str) -> None:
    asyncio.run(_run(uuid.UUID(run_id)))


async def _run(run_id: uuid.UUID) -> None:
    container = get_worker_container()
    try:
        async with container.session_factory() as session:
            store = PostgresRunStore(session)
            run = await store.load(run_id)
            if run is None or is_terminal(run.status):
                _logger.info("agent_run_skip", run_id=str(run_id))
                return
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
                        reranker=container.reranker,
                        rerank_blend=container.settings.rerank_blend,
                        compression=container.compression_policy,
                    ),
                    CodeEditProvider(storage=container.workspace_storage),
                    SandboxToolProvider(
                        sandbox=container.sandbox,
                        storage=container.workspace_storage,
                        events=events,
                        allow_network_installs=(container.settings.sandbox_allow_network_installs),
                    ),
                ],
                events=events,
            )
            memory_service = MemoryService(
                store=PostgresMemoryStore(session),
                vectors=container.memory_vector_index,
                embedder=container.dense_embedder,
            )
            nodes = GraphNodes(
                gateway=gateway,
                registry=registry,
                store=store,
                events=events,
                git=GitWorkflowService(
                    git=container.git_provider, storage=container.workspace_storage
                ),
                pr=PrService(
                    store=PostgresWorkspaceStore(session),
                    storage=container.workspace_storage,
                    git=container.git_provider,
                    pr_provider=container.pr_provider,
                    cipher=container.cipher,
                    audit=AuditLogger(session),
                ),
                memory=memory_service,
            )
            config = {"configurable": {"thread_id": str(run_id)}}
            async with AsyncPostgresSaver.from_conn_string(
                container.settings.checkpointer_dsn
            ) as saver:
                await saver.setup()  # idempotent: creates the checkpoint tables once
                graph = build_run_graph(nodes, checkpointer=saver)
                if run.status is RunStatus.PENDING:
                    final = await graph.ainvoke(
                        initial_state(
                            run_id=str(run_id),
                            owner_id=str(run.owner_id),
                            workspace_id=(str(run.workspace_id) if run.workspace_id else None),
                            goal=run.goal,
                        ),
                        config,
                    )
                else:
                    # Resumed after a human approved the plan (or an approval).
                    final = await graph.ainvoke(Command(resume="approved"), config)
            # End-of-run distillation: the only automatic memory writer (M11).
            if final.get("status") == RunStatus.COMPLETED.value:
                await MemoryDistiller(gateway=gateway, memory=memory_service).distill(
                    run_id=run_id,
                    owner_id=run.owner_id,
                    workspace_id=run.workspace_id,
                    goal=run.goal,
                    transcript=[str(t) for t in final.get("transcript", [])],
                )
            await session.commit()
    except Exception as exc:
        # Record the failure so the run never sticks in RUNNING, then re-raise so
        # Celery logs it with a traceback.
        await _mark_failed(run_id, str(exc))
        raise
    _logger.info("agent_run_done", run_id=str(run_id))


async def _mark_failed(run_id: uuid.UUID, error: str) -> None:
    """Record a crashed run as FAILED in a fresh session (the run's own session is
    poisoned by the exception), so it never sticks in RUNNING."""
    container = get_worker_container()
    async with container.session_factory() as session:
        store = PostgresRunStore(session)
        run = await store.load(run_id)
        if run is None or is_terminal(run.status):
            return
        await store.set_status(run_id=run_id, status=RunStatus.FAILED, error=error[:2000])
        OutboxWriter(session).add(
            EventEnvelope.of(
                RunStatusChanged(status=RunStatus.FAILED.value),
                run_id=run_id,
                actor=str(run.owner_id),
            )
        )
        await session.commit()
        _logger.warning("agent_run_failed", run_id=str(run_id), error=error[:200])
