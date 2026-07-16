"""Postgres adapter for the run store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from spidey.agents.domain.runs import (
    Approval,
    ApprovalStatus,
    Plan,
    PlanStep,
    Run,
    RunBudget,
    RunStatus,
)
from spidey.agents.infrastructure.orm import ApprovalRecord, PlanRecord, RunRecord

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


class PostgresRunStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self, run: Run, *, budget: RunBudget) -> None:
        self._session.add(
            RunRecord(
                id=run.id,
                owner_id=run.owner_id,
                workspace_id=run.workspace_id,
                session_id=run.session_id,
                goal=run.goal,
                status=run.status.value,
                error=run.error,
                budget=budget.model_dump(mode="json"),
            )
        )
        await self._session.flush()

    async def get_run(self, *, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run | None:
        record = await self._session.get(RunRecord, run_id)
        if record is None or record.owner_id != owner_id:
            return None
        return _to_run(record)

    async def load(self, run_id: uuid.UUID) -> Run | None:
        """Unscoped fetch for the worker (a system context, not a user request)."""
        record = await self._session.get(RunRecord, run_id)
        return _to_run(record) if record is not None else None

    async def list_runs(self, owner_id: uuid.UUID) -> list[Run]:
        records = await self._session.scalars(
            select(RunRecord)
            .where(RunRecord.owner_id == owner_id)
            .order_by(RunRecord.created_at.desc())
        )
        return [_to_run(r) for r in records]

    async def set_status(
        self, *, run_id: uuid.UUID, status: RunStatus, error: str | None = None
    ) -> None:
        record = await self._session.get(RunRecord, run_id)
        if record is not None:
            record.status = status.value
            record.error = error
            record.updated_at = datetime.now(tz=UTC)
            await self._session.flush()

    async def get_budget(self, run_id: uuid.UUID) -> RunBudget | None:
        record = await self._session.get(RunRecord, run_id)
        return RunBudget.model_validate(record.budget) if record is not None else None

    async def set_budget(self, *, run_id: uuid.UUID, budget: RunBudget) -> None:
        record = await self._session.get(RunRecord, run_id)
        if record is not None:
            record.budget = budget.model_dump(mode="json")
            await self._session.flush()

    async def save_plan(self, *, run_id: uuid.UUID, plan: Plan) -> None:
        steps = [s.model_dump(mode="json") for s in plan.steps]
        await self._session.execute(
            pg_insert(PlanRecord)
            .values(run_id=run_id, version=plan.version, steps=steps)
            .on_conflict_do_update(
                index_elements=[PlanRecord.run_id],
                set_={"version": plan.version, "steps": steps},
            )
        )
        await self._session.flush()

    async def get_plan(self, run_id: uuid.UUID) -> Plan | None:
        record = await self._session.scalar(select(PlanRecord).where(PlanRecord.run_id == run_id))
        if record is None:
            return None
        return Plan(
            version=record.version,
            steps=[PlanStep.model_validate(s) for s in record.steps],
        )

    async def create_approval(self, approval: Approval) -> None:
        self._session.add(
            ApprovalRecord(
                id=approval.id,
                run_id=approval.run_id,
                tool=approval.tool,
                side_effect=approval.side_effect,
                arguments_preview=approval.arguments_preview,
                status=approval.status.value,
                requested_at=approval.requested_at,
            )
        )
        await self._session.flush()

    async def pending_approvals(self, run_id: uuid.UUID) -> list[Approval]:
        records = await self._session.scalars(
            select(ApprovalRecord).where(
                ApprovalRecord.run_id == run_id,
                ApprovalRecord.status == ApprovalStatus.PENDING.value,
            )
        )
        return [_to_approval(r) for r in records]

    async def get_approval(self, approval_id: uuid.UUID) -> Approval | None:
        record = await self._session.get(ApprovalRecord, approval_id)
        return _to_approval(record) if record is not None else None

    async def resolve_approval(
        self, *, approval_id: uuid.UUID, status: ApprovalStatus, decided_by: uuid.UUID
    ) -> None:
        record = await self._session.get(ApprovalRecord, approval_id)
        if record is not None:
            record.status = status.value
            record.decided_by = decided_by
            record.decided_at = datetime.now(tz=UTC)
            await self._session.flush()


def _to_run(record: RunRecord) -> Run:
    return Run(
        id=record.id,
        owner_id=record.owner_id,
        workspace_id=record.workspace_id,
        session_id=record.session_id,
        goal=record.goal,
        status=RunStatus(record.status),
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _to_approval(record: ApprovalRecord) -> Approval:
    return Approval(
        id=record.id,
        run_id=record.run_id,
        tool=record.tool,
        side_effect=record.side_effect,
        arguments_preview=record.arguments_preview,
        status=ApprovalStatus(record.status),
        requested_at=record.requested_at,
        decided_at=record.decided_at,
        decided_by=record.decided_by,
    )
