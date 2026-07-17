"""Run lifecycle service: transitions, plan edit, approvals — with a fake store."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from spidey.agents.application import RunService
from spidey.agents.domain import (
    Approval,
    ApprovalStatus,
    Plan,
    Run,
    RunBudget,
    RunStatus,
)
from spidey.platform.errors import ConflictError, NotFoundError

OWNER = uuid.uuid4()


class FakeStore:
    def __init__(self) -> None:
        self.runs: dict[uuid.UUID, Run] = {}
        self.budgets: dict[uuid.UUID, RunBudget] = {}
        self.plans: dict[uuid.UUID, Plan] = {}
        self.approvals: dict[uuid.UUID, Approval] = {}

    async def create_run(self, run: Run, *, budget: RunBudget) -> None:
        self.runs[run.id] = run
        self.budgets[run.id] = budget

    async def get_run(self, *, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run | None:
        run = self.runs.get(run_id)
        return run if run is not None and run.owner_id == owner_id else None

    async def list_runs(self, owner_id: uuid.UUID) -> list[Run]:
        return [r for r in self.runs.values() if r.owner_id == owner_id]

    async def set_status(
        self, *, run_id: uuid.UUID, status: RunStatus, error: str | None = None
    ) -> None:
        self.runs[run_id] = self.runs[run_id].model_copy(update={"status": status, "error": error})

    async def set_base_commit(self, *, run_id: uuid.UUID, base_commit: str | None) -> None:
        self.runs[run_id] = self.runs[run_id].model_copy(update={"base_commit": base_commit})

    async def get_budget(self, run_id: uuid.UUID) -> RunBudget | None:
        return self.budgets.get(run_id)

    async def set_budget(self, *, run_id: uuid.UUID, budget: RunBudget) -> None:
        self.budgets[run_id] = budget

    async def save_plan(self, *, run_id: uuid.UUID, plan: Plan) -> None:
        self.plans[run_id] = plan

    async def get_plan(self, run_id: uuid.UUID) -> Plan | None:
        return self.plans.get(run_id)

    async def create_approval(self, approval: Approval) -> None:
        self.approvals[approval.id] = approval

    async def pending_approvals(self, run_id: uuid.UUID) -> list[Approval]:
        return [
            a
            for a in self.approvals.values()
            if a.run_id == run_id and a.status is ApprovalStatus.PENDING
        ]

    async def get_approval(self, approval_id: uuid.UUID) -> Approval | None:
        return self.approvals.get(approval_id)

    async def resolve_approval(
        self, *, approval_id: uuid.UUID, status: ApprovalStatus, decided_by: uuid.UUID
    ) -> None:
        self.approvals[approval_id] = self.approvals[approval_id].model_copy(
            update={"status": status, "decided_by": decided_by}
        )


class FakeEvents:
    def __init__(self) -> None:
        self.types: list[str] = []

    def add(self, envelope: object) -> None:
        self.types.append(envelope.event_type)  # type: ignore[attr-defined]


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    def enqueue(self, task_name: str, *args: str, queue: str | None = None) -> None:
        self.enqueued.append(args[0])


def _service() -> tuple[RunService, FakeStore, FakeEvents, FakeQueue]:
    store, events, queue = FakeStore(), FakeEvents(), FakeQueue()
    return RunService(store=store, events=events, task_queue=queue), store, events, queue


def _seed(store: FakeStore, status: RunStatus) -> uuid.UUID:
    run_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    store.runs[run_id] = Run(
        id=run_id,
        owner_id=OWNER,
        workspace_id=None,
        session_id=None,
        goal="do it",
        status=status,
        created_at=now,
        updated_at=now,
    )
    store.budgets[run_id] = RunBudget()
    return run_id


class TestLifecycle:
    async def test_create_starts_and_enqueues(self) -> None:
        svc, store, events, queue = _service()
        run = await svc.create(owner_id=OWNER, goal="fix the bug")
        assert run.status is RunStatus.PENDING
        assert store.runs[run.id].goal == "fix the bug"
        assert "agents.run_started" in events.types
        assert queue.enqueued == [str(run.id)]

    async def test_get_is_owner_scoped(self) -> None:
        svc, store, _e, _q = _service()
        run_id = _seed(store, RunStatus.RUNNING)
        with pytest.raises(NotFoundError):
            await svc.get(owner_id=uuid.uuid4(), run_id=run_id)

    async def test_cancel_running(self) -> None:
        svc, store, events, _q = _service()
        run_id = _seed(store, RunStatus.RUNNING)
        run = await svc.cancel(owner_id=OWNER, run_id=run_id)
        assert run.status is RunStatus.CANCELLED
        assert store.runs[run_id].status is RunStatus.CANCELLED
        assert "agents.run_status_changed" in events.types

    async def test_cancel_terminal_conflicts(self) -> None:
        svc, store, _e, _q = _service()
        run_id = _seed(store, RunStatus.COMPLETED)
        with pytest.raises(ConflictError):
            await svc.cancel(owner_id=OWNER, run_id=run_id)

    async def test_edit_plan_before_execution(self) -> None:
        svc, store, events, _q = _service()
        run_id = _seed(store, RunStatus.AWAITING_APPROVAL)
        plan = await svc.edit_plan(
            owner_id=OWNER,
            run_id=run_id,
            steps=[{"index": 0, "title": "read code"}],
        )
        assert plan.version == 1
        assert store.plans[run_id].steps[0].title == "read code"
        assert "agents.plan_created" in events.types

    async def test_edit_plan_after_start_conflicts(self) -> None:
        svc, store, _e, _q = _service()
        run_id = _seed(store, RunStatus.RUNNING)
        with pytest.raises(ConflictError):
            await svc.edit_plan(owner_id=OWNER, run_id=run_id, steps=[])

    async def test_resume_requires_paused(self) -> None:
        svc, store, _e, _q = _service()
        run_id = _seed(store, RunStatus.RUNNING)
        with pytest.raises(ConflictError):
            await svc.resume(owner_id=OWNER, run_id=run_id)

    async def test_resume_from_needs_human(self) -> None:
        svc, store, _e, queue = _service()
        run_id = _seed(store, RunStatus.NEEDS_HUMAN)
        run = await svc.resume(owner_id=OWNER, run_id=run_id)
        assert run.status is RunStatus.RUNNING
        assert queue.enqueued == [str(run_id)]


class TestApprovals:
    def _pending(self, store: FakeStore, run_id: uuid.UUID) -> uuid.UUID:
        approval_id = uuid.uuid4()
        store.approvals[approval_id] = Approval(
            id=approval_id,
            run_id=run_id,
            tool="git.commit",
            side_effect="write",
            arguments_preview="commit -m ...",
            requested_at=datetime.now(tz=UTC),
        )
        return approval_id

    async def test_approve_last_pending_resumes(self) -> None:
        svc, store, events, queue = _service()
        run_id = _seed(store, RunStatus.AWAITING_APPROVAL)
        approval_id = self._pending(store, run_id)
        await svc.resolve_approval(
            owner_id=OWNER, run_id=run_id, approval_id=approval_id, approved=True
        )
        assert store.approvals[approval_id].status is ApprovalStatus.APPROVED
        assert store.runs[run_id].status is RunStatus.RUNNING
        assert queue.enqueued == [str(run_id)]
        assert "agents.approval_resolved" in events.types

    async def test_reject_cancels_run(self) -> None:
        svc, store, _e, _q = _service()
        run_id = _seed(store, RunStatus.AWAITING_APPROVAL)
        approval_id = self._pending(store, run_id)
        await svc.resolve_approval(
            owner_id=OWNER, run_id=run_id, approval_id=approval_id, approved=False
        )
        assert store.runs[run_id].status is RunStatus.CANCELLED

    async def test_resume_blocked_by_pending_approval(self) -> None:
        svc, store, _e, _q = _service()
        run_id = _seed(store, RunStatus.AWAITING_APPROVAL)
        self._pending(store, run_id)
        with pytest.raises(ConflictError):
            await svc.resume(owner_id=OWNER, run_id=run_id)
