"""Agent runs: lifecycle control (REST) + event streaming (SSE).

The run is the durable unit of agent work (M7). A client creates a run with a
goal, watches it plan, approves or edits the plan, resolves any side-effect
approvals, and streams the timeline over SSE. Client→server actions are ordinary
owner-scoped REST posts; the ``/events`` channel is unidirectional by design
(ADR-0006). The scripted chat (M6) keeps its own ``POST /runs/chat`` entrypoint
and shares the same SSE stream.

Authorization: every lifecycle call is owner-scoped in :class:`RunService` (a
non-owner sees the run as not found); the SSE stream additionally checks a Redis
owner record written at creation time so it can authorize without a DB round-trip.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from spidey.agents.application import RunReport, build_run_report
from spidey.agents.domain.runs import (
    Approval,
    Plan,
    Run,
    RunBudget,
    RunStatus,
)
from spidey.api.deps import CurrentUser, RequireDeveloper, RunServiceDep, SessionDep
from spidey.platform.errors import NotFoundError
from spidey.platform.events import RunEventReader, stream_key_for
from spidey.workspaces.application import GitWorkflowService, branch_for_run

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from redis.asyncio import Redis

    from spidey.platform.events import StreamBus

router = APIRouter(prefix="/runs", tags=["runs"])

_CHAT_TASK = "spidey.agents.chat"


# ── request/response models ──────────────────────────────────────────────────
class BudgetRequest(BaseModel):
    """Optional per-run ceilings; omitted fields fall back to the run defaults."""

    max_steps: int = Field(default=25, ge=1, le=200)
    max_tokens: int = Field(default=500_000, ge=1000)
    max_cost_usd: float = Field(default=5.0, gt=0, le=100)


class CreateRunRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=8192)
    workspace_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    budget: BudgetRequest | None = None


class RunResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    workspace_id: uuid.UUID | None
    session_id: uuid.UUID | None
    goal: str
    status: RunStatus
    error: str | None
    base_commit: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, run: Run) -> RunResponse:
        return cls.model_validate(run, from_attributes=True)


class PlanStepModel(BaseModel):
    index: int
    title: str = Field(min_length=1, max_length=500)
    detail: str = ""
    status: str = "pending"


class PlanResponse(BaseModel):
    version: int
    steps: list[PlanStepModel]

    @classmethod
    def of(cls, plan: Plan) -> PlanResponse:
        return cls.model_validate(plan, from_attributes=True)


class EditPlanRequest(BaseModel):
    steps: list[PlanStepModel] = Field(min_length=1, max_length=50)


class ApprovalResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    tool: str
    side_effect: str
    arguments_preview: str
    status: str
    requested_at: datetime
    decided_at: datetime | None
    decided_by: uuid.UUID | None

    @classmethod
    def of(cls, approval: Approval) -> ApprovalResponse:
        return cls.model_validate(approval, from_attributes=True)


class ResolveApprovalRequest(BaseModel):
    approved: bool


# ── run lifecycle ────────────────────────────────────────────────────────────
@router.post(
    "",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an agent run (streams at /runs/{run_id}/events)",
)
async def create_run(
    request: Request,
    body: CreateRunRequest,
    service: RunServiceDep,
    developer: RequireDeveloper,
) -> RunResponse:
    budget = (
        RunBudget(
            max_steps=body.budget.max_steps,
            max_tokens=body.budget.max_tokens,
            max_cost_usd=body.budget.max_cost_usd,
        )
        if body.budget is not None
        else None
    )
    run = await service.create(
        owner_id=developer.id,
        goal=body.goal,
        workspace_id=body.workspace_id,
        session_id=body.session_id,
        budget=budget,
    )
    # Record ownership so the SSE stream authorizes immediately (mirrors chat).
    await set_run_owner(request.app.state.container.redis, run.id, developer.id)
    return RunResponse.of(run)


@router.get("", response_model=list[RunResponse], summary="List my runs")
async def list_runs(service: RunServiceDep, user: CurrentUser) -> list[RunResponse]:
    runs = await service.list(user.id)
    return [RunResponse.of(r) for r in runs]


@router.get("/{run_id}", response_model=RunResponse, summary="Get a run")
async def get_run(run_id: uuid.UUID, service: RunServiceDep, user: CurrentUser) -> RunResponse:
    run = await service.get(owner_id=user.id, run_id=run_id)
    return RunResponse.of(run)


@router.post("/{run_id}/cancel", response_model=RunResponse, summary="Cancel a run")
async def cancel_run(
    run_id: uuid.UUID, service: RunServiceDep, developer: RequireDeveloper
) -> RunResponse:
    run = await service.cancel(owner_id=developer.id, run_id=run_id)
    return RunResponse.of(run)


@router.post(
    "/{run_id}/resume",
    response_model=RunResponse,
    summary="Resume a paused run (plan approved / budget lifted)",
)
async def resume_run(
    run_id: uuid.UUID, service: RunServiceDep, developer: RequireDeveloper
) -> RunResponse:
    run = await service.resume(owner_id=developer.id, run_id=run_id)
    return RunResponse.of(run)


# ── plan ─────────────────────────────────────────────────────────────────────
@router.get("/{run_id}/plan", response_model=PlanResponse, summary="Get a run's plan")
async def get_plan(run_id: uuid.UUID, service: RunServiceDep, user: CurrentUser) -> PlanResponse:
    plan = await service.get_plan(owner_id=user.id, run_id=run_id)
    if plan is None:
        raise NotFoundError("plan not found")
    return PlanResponse.of(plan)


@router.put(
    "/{run_id}/plan",
    response_model=PlanResponse,
    summary="Edit a run's plan before execution",
)
async def edit_plan(
    run_id: uuid.UUID,
    body: EditPlanRequest,
    service: RunServiceDep,
    developer: RequireDeveloper,
) -> PlanResponse:
    steps = [s.model_dump() for s in body.steps]
    plan = await service.edit_plan(owner_id=developer.id, run_id=run_id, steps=steps)
    return PlanResponse.of(plan)


# ── approvals ────────────────────────────────────────────────────────────────
@router.get(
    "/{run_id}/approvals",
    response_model=list[ApprovalResponse],
    summary="List a run's pending side-effect approvals",
)
async def list_approvals(
    run_id: uuid.UUID, service: RunServiceDep, user: CurrentUser
) -> list[ApprovalResponse]:
    approvals = await service.pending_approvals(owner_id=user.id, run_id=run_id)
    return [ApprovalResponse.of(a) for a in approvals]


@router.post(
    "/{run_id}/approvals/{approval_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve or reject a pending side-effect",
)
async def resolve_approval(
    run_id: uuid.UUID,
    approval_id: uuid.UUID,
    body: ResolveApprovalRequest,
    service: RunServiceDep,
    developer: RequireDeveloper,
) -> None:
    await service.resolve_approval(
        owner_id=developer.id,
        run_id=run_id,
        approval_id=approval_id,
        approved=body.approved,
    )


# ── timeline (durable reconstruction) ────────────────────────────────────────
class TimelineEvent(BaseModel):
    event_id: str
    event_type: str
    occurred_at: datetime
    actor: str | None
    payload: dict[str, object]


@router.get(
    "/{run_id}/timeline",
    response_model=list[TimelineEvent],
    summary="Reconstruct a run's persisted event timeline (replay/audit)",
)
async def get_timeline(
    run_id: uuid.UUID,
    service: RunServiceDep,
    session: SessionDep,
    user: CurrentUser,
) -> list[TimelineEvent]:
    # Owner-scoped: raises not-found for a non-owner before any event is read.
    await service.get(owner_id=user.id, run_id=run_id)
    events = await RunEventReader(session).timeline(run_id)
    return [
        TimelineEvent(
            event_id=str(e.event_id),
            event_type=e.event_type,
            occurred_at=e.occurred_at,
            actor=e.actor,
            payload=e.payload,
        )
        for e in events
    ]


@router.get(
    "/{run_id}/report",
    response_model=RunReport,
    summary="Structured run report (plan, commits, tests, PR, outcome)",
)
async def get_report(
    run_id: uuid.UUID,
    service: RunServiceDep,
    session: SessionDep,
    user: CurrentUser,
) -> RunReport:
    run = await service.get(owner_id=user.id, run_id=run_id)  # owner-scoped
    plan = await service.get_plan(owner_id=user.id, run_id=run_id)
    events = await RunEventReader(session).timeline(run_id)
    return build_run_report(run, plan, events)


# ── diff (M8): what the run changed on its isolated branch ──────────────────
class RunDiffResponse(BaseModel):
    branch: str
    base_commit: str | None
    diff: str


@router.get(
    "/{run_id}/diff",
    response_model=RunDiffResponse,
    summary="Unified diff of the run's branch (committed steps + working tree)",
)
async def get_run_diff(
    run_id: uuid.UUID,
    request: Request,
    service: RunServiceDep,
    user: CurrentUser,
) -> RunDiffResponse:
    run = await service.get(owner_id=user.id, run_id=run_id)  # owner-scoped
    if run.workspace_id is None:
        raise NotFoundError("run has no workspace")
    container = request.app.state.container
    workflow = GitWorkflowService(git=container.git_provider, storage=container.workspace_storage)
    diff = await workflow.run_diff(workspace_id=run.workspace_id, base=run.base_commit)
    return RunDiffResponse(branch=branch_for_run(run_id), base_commit=run.base_commit, diff=diff)


# ── scripted chat (M6) ───────────────────────────────────────────────────────
class ChatStartRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8192)
    session_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None


class RunCreatedResponse(BaseModel):
    run_id: uuid.UUID


@router.post(
    "/chat",
    response_model=RunCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a scripted chat run (streams at /runs/{run_id}/events)",
)
async def start_chat(
    request: Request,
    body: ChatStartRequest,
    developer: RequireDeveloper,
) -> RunCreatedResponse:
    container = request.app.state.container
    run_id = uuid.uuid4()
    # Record ownership before enqueue so the SSE stream authorizes immediately.
    await set_run_owner(container.redis, run_id, developer.id)
    container.task_queue.enqueue(
        _CHAT_TASK,
        str(run_id),
        str(developer.id),
        developer.role.value,
        body.message,
        str(body.session_id) if body.session_id else "",
        str(body.workspace_id) if body.workspace_id else "",
        queue="ingestion",
    )
    return RunCreatedResponse(run_id=run_id)


# ── event stream (SSE) ───────────────────────────────────────────────────────
# Short server-side block so client disconnects are noticed promptly and a
# keep-alive comment is emitted through idle periods.
_BLOCK_MS = 2000
_READ_COUNT = 100
_OWNER_TTL_SECONDS = 24 * 3600


def _owner_key(run_id: uuid.UUID) -> str:
    return f"run:{run_id}:owner"


async def set_run_owner(redis: Redis, run_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    """Record who may stream a run (ephemeral, TTL-bounded)."""
    await redis.set(_owner_key(run_id), str(owner_id), ex=_OWNER_TTL_SECONDS)


@router.get(
    "/{run_id}/events",
    summary="Stream a run's events (SSE)",
    response_class=StreamingResponse,
)
async def stream_run_events(
    run_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    container = request.app.state.container
    owner = await container.redis.get(_owner_key(run_id))
    if owner != str(user.id):
        raise NotFoundError("run not found")

    bus: StreamBus = container.stream_bus
    stream_key = stream_key_for(run_id)
    # No cursor → replay the retained stream from the start; else resume after it.
    cursor = last_event_id or "0"

    async def events() -> AsyncIterator[str]:
        nonlocal cursor
        while not await request.is_disconnected():
            messages = await bus.read(
                stream_key, last_id=cursor, block_ms=_BLOCK_MS, count=_READ_COUNT
            )
            if not messages:
                yield ": keep-alive\n\n"
                continue
            for message_id, data in messages:
                cursor = message_id
                yield f"id: {message_id}\ndata: {data}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
