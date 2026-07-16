"""Run lifecycle service (M7).

Owns the state machine and the human-in-the-loop gates: creating a run enqueues
the graph; a human can edit the plan or resolve an approval; a resume re-enters
the graph after a pause; every transition is guarded by ``can_transition`` and
published as an event. The graph itself (LangGraph) executes in the worker; this
service is the durable, owner-scoped control surface the API and UI drive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spidey.agents.domain.runs import (
    Approval,
    ApprovalStatus,
    Plan,
    Run,
    RunBudget,
    RunStatus,
    can_transition,
    is_terminal,
)
from spidey.platform.errors import ConflictError, NotFoundError
from spidey.platform.events import (
    ApprovalResolved,
    EventEnvelope,
    PlanCreated,
    RunStarted,
    RunStatusChanged,
)

if TYPE_CHECKING:
    from spidey.agents.domain.ports import RunStore
    from spidey.platform.events import EventPublisher
    from spidey.platform.tasks import TaskQueue

_RUN_TASK = "spidey.agents.run"


class RunService:
    def __init__(
        self, *, store: RunStore, events: EventPublisher, task_queue: TaskQueue
    ) -> None:
        self._store = store
        self._events = events
        self._tasks = task_queue

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        goal: str,
        workspace_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        budget: RunBudget | None = None,
    ) -> Run:
        now = datetime.now(tz=UTC)
        run = Run(
            id=uuid.uuid4(),
            owner_id=owner_id,
            workspace_id=workspace_id,
            session_id=session_id,
            goal=goal,
            status=RunStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        await self._store.create_run(run, budget=budget or RunBudget())
        self._events.add(
            EventEnvelope.of(
                RunStarted(goal=goal),
                run_id=run.id,
                workspace_id=workspace_id,
                session_id=session_id,
                actor=str(owner_id),
            )
        )
        self._enqueue(run.id)
        return run

    async def get(self, *, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run:
        return await self._require(owner_id, run_id)

    async def list(self, owner_id: uuid.UUID) -> list[Run]:
        return await self._store.list_runs(owner_id)

    async def get_plan(self, *, owner_id: uuid.UUID, run_id: uuid.UUID) -> Plan | None:
        await self._require(owner_id, run_id)
        return await self._store.get_plan(run_id)

    async def edit_plan(
        self, *, owner_id: uuid.UUID, run_id: uuid.UUID, steps: list[dict[str, object]]
    ) -> Plan:
        run = await self._require(owner_id, run_id)
        if run.status not in {RunStatus.PLANNING, RunStatus.AWAITING_APPROVAL}:
            raise ConflictError("plan can only be edited before execution")
        existing = await self._store.get_plan(run_id)
        version = (existing.version + 1) if existing else 1
        plan = Plan.model_validate({"version": version, "steps": steps})
        await self._store.save_plan(run_id=run_id, plan=plan)
        self._events.add(
            EventEnvelope.of(
                PlanCreated(version=version, step_count=len(plan.steps)),
                run_id=run_id,
                actor=str(owner_id),
            )
        )
        return plan

    async def cancel(self, *, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run:
        run = await self._require(owner_id, run_id)
        if is_terminal(run.status):
            raise ConflictError("run has already finished")
        return await self._transition(run, RunStatus.CANCELLED, actor=owner_id)

    async def resume(self, *, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run:
        run = await self._require(owner_id, run_id)
        if run.status not in {RunStatus.NEEDS_HUMAN, RunStatus.AWAITING_APPROVAL}:
            raise ConflictError("run is not paused")
        if await self._store.pending_approvals(run_id):
            raise ConflictError("run has unresolved approvals")
        resumed = await self._transition(run, RunStatus.RUNNING, actor=owner_id)
        self._enqueue(run_id)
        return resumed

    async def pending_approvals(
        self, *, owner_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[Approval]:
        await self._require(owner_id, run_id)
        return await self._store.pending_approvals(run_id)

    async def resolve_approval(
        self,
        *,
        owner_id: uuid.UUID,
        run_id: uuid.UUID,
        approval_id: uuid.UUID,
        approved: bool,
    ) -> None:
        run = await self._require(owner_id, run_id)
        approval = await self._store.get_approval(approval_id)
        if approval is None or approval.run_id != run_id:
            raise NotFoundError("approval not found")
        if approval.status is not ApprovalStatus.PENDING:
            raise ConflictError("approval already resolved")
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        await self._store.resolve_approval(
            approval_id=approval_id, status=status, decided_by=owner_id
        )
        self._events.add(
            EventEnvelope.of(
                ApprovalResolved(approval_id=approval_id, approved=approved),
                run_id=run_id,
                actor=str(owner_id),
            )
        )
        if not approved:
            # A rejected side effect stops the run; the human decides next steps.
            await self._transition(run, RunStatus.CANCELLED, actor=owner_id)
        elif not await self._store.pending_approvals(run_id):
            await self._transition(run, RunStatus.RUNNING, actor=owner_id)
            self._enqueue(run_id)

    # ── internals ────────────────────────────────────────────────────────────
    async def _require(self, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run:
        run = await self._store.get_run(owner_id=owner_id, run_id=run_id)
        if run is None:
            raise NotFoundError("run not found")
        return run

    async def _transition(self, run: Run, target: RunStatus, *, actor: uuid.UUID) -> Run:
        if not can_transition(run.status, target):
            raise ConflictError(f"cannot move run from {run.status.value} to {target.value}")
        await self._store.set_status(run_id=run.id, status=target)
        self._events.add(
            EventEnvelope.of(
                RunStatusChanged(status=target.value),
                run_id=run.id,
                actor=str(actor),
            )
        )
        return run.model_copy(update={"status": target})

    def _enqueue(self, run_id: uuid.UUID) -> None:
        self._tasks.enqueue(_RUN_TASK, str(run_id), queue="ingestion")
