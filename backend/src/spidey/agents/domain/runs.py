"""Agent-run domain: lifecycle, editable plans, budgets, approvals (M7).

A ``Run`` is a durable, resumable unit of agent work (ADR-0002). Its status is a
small state machine — the graph advances it, humans gate it, and budgets can
halt it into ``needs_human`` rather than letting it run away (NFR-5). Plans are
structured and editable so a human can steer before execution; every
side-effecting action beyond ``read`` requires a recorded :class:`Approval`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    PENDING = "pending"  # created, not yet started
    PLANNING = "planning"  # planner is producing a plan
    AWAITING_APPROVAL = "awaiting_approval"  # paused on a human gate (plan or tool)
    RUNNING = "running"  # executing plan steps
    NEEDS_HUMAN = "needs_human"  # budget/step exhaustion or an unrecoverable ask
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED})

# Allowed status transitions — the run service and graph honor exactly these.
_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.PLANNING, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.PLANNING: frozenset(
        {RunStatus.AWAITING_APPROVAL, RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.AWAITING_APPROVAL: frozenset(
        {RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.NEEDS_HUMAN}
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.AWAITING_APPROVAL,
            RunStatus.NEEDS_HUMAN,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.NEEDS_HUMAN: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.FAILED}),
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


def is_terminal(status: RunStatus) -> bool:
    return status in _TERMINAL


class Run(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    workspace_id: uuid.UUID | None
    session_id: uuid.UUID | None
    goal: str
    status: RunStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class RunBudget(BaseModel):
    """Per-run ceilings and consumption. Exhaustion → ``needs_human`` (NFR-5)."""

    model_config = ConfigDict(frozen=True)

    max_steps: int = 25
    max_tokens: int = 500_000
    max_cost_usd: float = 5.0
    steps_used: int = 0
    tokens_used: int = 0
    cost_used: float = 0.0

    def exhausted(self) -> bool:
        return (
            self.steps_used >= self.max_steps
            or self.tokens_used >= self.max_tokens
            or self.cost_used >= self.max_cost_usd
        )


class StepStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    SKIPPED = "skipped"


class PlanStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    title: str
    detail: str = ""
    status: StepStatus = StepStatus.PENDING


class Plan(BaseModel):
    """A structured, human-editable plan. ``version`` bumps on each edit so a
    resume after an edit uses the approved revision."""

    model_config = ConfigDict(frozen=True)

    version: int = 1
    steps: list[PlanStep] = Field(default_factory=list[PlanStep])


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Approval(BaseModel):
    """A recorded gate for a side-effecting action. No write/destructive tool
    runs without one resolved ``approved`` (the security invariant of M7)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    run_id: uuid.UUID
    tool: str
    side_effect: str
    arguments_preview: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: uuid.UUID | None = None
