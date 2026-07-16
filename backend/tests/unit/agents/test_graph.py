"""The agent graph, offline: plan → approval interrupt → resume → execute →
complete, with an in-memory checkpointer and fake services (ADR-0009)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from spidey.agents.application import ToolRegistry
from spidey.agents.domain import Plan, RunStatus
from spidey.agents.domain.runs import RunBudget
from spidey.agents.graph import GraphNodes, build_run_graph, initial_state
from spidey.llm.domain import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FinishReason,
    MessageRole,
    Role,
    Usage,
)

if TYPE_CHECKING:
    from spidey.agents.domain.runs import Approval, ApprovalStatus, Run


class FakeGateway:
    def __init__(self) -> None:
        self.roles: list[Role] = []

    async def complete(
        self,
        *,
        role: Role,
        request: ChatRequest,
        run_id: object = None,
        session_id: object = None,
        actor: object = None,
        budget_scope: object = None,
    ) -> ChatResponse:
        self.roles.append(role)
        text = "read the code\nsummarize" if role is Role.PLANNER else "step done"
        return ChatResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content=text),
            finish_reason=FinishReason.STOP,
            usage=Usage(prompt_tokens=5, completion_tokens=3),
            provider="fake",
            model="m",
        )


class FakeStore:
    def __init__(self, budget: RunBudget | None = None) -> None:
        self.plan: Plan | None = None
        self.statuses: list[RunStatus] = []
        self.budget = budget

    async def save_plan(self, *, run_id: uuid.UUID, plan: Plan) -> None:
        self.plan = plan

    async def get_plan(self, run_id: uuid.UUID) -> Plan | None:
        return self.plan

    async def set_status(
        self, *, run_id: uuid.UUID, status: RunStatus, error: str | None = None
    ) -> None:
        self.statuses.append(status)

    async def create_approval(self, approval: Approval) -> None: ...
    async def create_run(self, run: Run, *, budget: RunBudget) -> None: ...
    async def get_run(self, *, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run | None:
        return None

    async def list_runs(self, owner_id: uuid.UUID) -> list[Run]:
        return []

    async def get_budget(self, run_id: uuid.UUID) -> RunBudget | None:
        return self.budget

    async def set_budget(self, *, run_id: uuid.UUID, budget: RunBudget) -> None:
        self.budget = budget

    async def pending_approvals(self, run_id: uuid.UUID) -> list[Approval]:
        return []

    async def get_approval(self, approval_id: uuid.UUID) -> Approval | None:
        return None

    async def resolve_approval(
        self, *, approval_id: uuid.UUID, status: ApprovalStatus, decided_by: uuid.UUID
    ) -> None: ...


class FakeEvents:
    def __init__(self) -> None:
        self.types: list[str] = []

    def add(self, envelope: object) -> None:
        self.types.append(envelope.event_type)  # type: ignore[attr-defined]


async def test_plan_interrupt_resume_execute_complete() -> None:
    gateway, store, events = FakeGateway(), FakeStore(), FakeEvents()
    nodes = GraphNodes(
        gateway=gateway,  # type: ignore[arg-type]
        registry=ToolRegistry(providers=[]),
        store=store,  # type: ignore[arg-type]
        events=events,  # type: ignore[arg-type]
    )
    graph = build_run_graph(nodes, checkpointer=MemorySaver())

    run_id, owner_id = uuid.uuid4(), uuid.uuid4()
    config = {"configurable": {"thread_id": str(run_id)}}
    state = initial_state(
        run_id=str(run_id), owner_id=str(owner_id), workspace_id=None, goal="ship it"
    )

    # First pass: plans, then pauses at the plan-approval interrupt.
    result = await graph.ainvoke(state, config)
    assert "__interrupt__" in result
    assert store.plan is not None
    assert [s.title for s in store.plan.steps] == ["read the code", "summarize"]
    assert RunStatus.AWAITING_APPROVAL in store.statuses
    snapshot = await graph.aget_state(config)
    assert snapshot.next  # the run is paused, not finished

    # Human approves; resume runs both steps and finalizes.
    final = await graph.ainvoke(Command(resume="approved"), config)
    assert final["status"] == RunStatus.COMPLETED.value
    assert final["step_index"] == 2  # two steps executed
    assert RunStatus.COMPLETED in store.statuses
    assert "agents.plan_created" in events.types
    assert "chat.run_completed" in events.types
    # Planner ran once; coder ran once per step.
    assert gateway.roles.count(Role.PLANNER) == 1
    assert gateway.roles.count(Role.CODER) == 2


async def test_budget_exhaustion_pauses_then_resumes() -> None:
    # A one-step budget against a two-step plan: the run must pause after step 1
    # (NEEDS_HUMAN), then a resume grants a fresh window and it completes (NFR-5).
    gateway, events = FakeGateway(), FakeEvents()
    store = FakeStore(budget=RunBudget(max_steps=1))
    nodes = GraphNodes(
        gateway=gateway,  # type: ignore[arg-type]
        registry=ToolRegistry(providers=[]),
        store=store,  # type: ignore[arg-type]
        events=events,  # type: ignore[arg-type]
    )
    graph = build_run_graph(nodes, checkpointer=MemorySaver())
    run_id, owner_id = uuid.uuid4(), uuid.uuid4()
    config = {"configurable": {"thread_id": str(run_id)}}
    state = initial_state(
        run_id=str(run_id), owner_id=str(owner_id), workspace_id=None, goal="ship it"
    )

    # Plan → approve → step 1 runs → budget spent → pause at the budget gate.
    await graph.ainvoke(state, config)
    await graph.ainvoke(Command(resume="approved"), config)  # approve the plan
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("budget_gate",)
    assert RunStatus.NEEDS_HUMAN in store.statuses

    # Human grants another window; the run finishes the remaining step.
    final = await graph.ainvoke(Command(resume="granted"), config)
    assert final["status"] == RunStatus.COMPLETED.value
    assert final["step_index"] == 2
    assert store.budget is not None
    assert store.budget.steps_used == 1  # window reset to 0, then step 2 charged


def test_registry_spec_lookup() -> None:
    registry = ToolRegistry(providers=[])
    assert registry.spec_for("nope") is None
