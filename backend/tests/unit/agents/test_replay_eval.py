"""M7 exit criterion: a completed run replays deterministically from fixtures.

Drives the real agent graph with a fixture gateway (scripted planner/coder
responses) and an in-memory checkpointer, reconstructs the run timeline, and
grades it with :class:`AgentReplayEvalSuite` against the committed golden
(``evaluation/datasets/agent_replay/``). No model, network, or database — this
is the deterministic replay the T1 gate depends on.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from spidey.agents.application import ToolRegistry
from spidey.agents.graph import GraphNodes, build_run_graph, initial_state
from spidey.evaluation.application import AgentReplayEvalSuite
from spidey.evaluation.domain import ReplayCase, ReplayTimeline
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
    from spidey.agents.domain.runs import Plan, RunStatus

_FIXTURES = Path(__file__).resolve().parents[4] / "evaluation" / "datasets" / "agent_replay"


class _FixtureGateway:
    """Replays scripted responses: the plan for the planner, a note per coder step."""

    def __init__(self, *, planner_lines: list[str], coder_notes: list[str]) -> None:
        self._plan = "\n".join(planner_lines)
        self._notes = list(coder_notes)
        self._index = 0

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
        if role is Role.PLANNER:
            text = self._plan
        else:
            text = self._notes[self._index]
            self._index += 1
        return ChatResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content=text),
            finish_reason=FinishReason.STOP,
            usage=Usage(prompt_tokens=5, completion_tokens=3),
            provider="fixture",
            model="m",
        )


class _FakeStore:
    def __init__(self) -> None:
        self.plan: Plan | None = None

    async def save_plan(self, *, run_id: uuid.UUID, plan: Plan) -> None:
        self.plan = plan

    async def get_plan(self, run_id: uuid.UUID) -> Plan | None:
        return self.plan

    async def set_status(
        self, *, run_id: uuid.UUID, status: RunStatus, error: str | None = None
    ) -> None: ...

    async def get_budget(self, run_id: uuid.UUID) -> None:
        return None

    async def set_budget(self, *, run_id: uuid.UUID, budget: object) -> None: ...


class _FakeEvents:
    def __init__(self) -> None:
        self.types: list[str] = []

    def add(self, envelope: object) -> None:
        self.types.append(envelope.event_type)  # type: ignore[attr-defined]


async def _drive(case: ReplayCase) -> ReplayTimeline:
    gateway = _FixtureGateway(planner_lines=case.planner_lines, coder_notes=case.coder_notes)
    store, events = _FakeStore(), _FakeEvents()
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
        run_id=str(run_id), owner_id=str(owner_id), workspace_id=None, goal=case.goal
    )
    await graph.ainvoke(state, config)  # plan → pause at approval
    final = await graph.ainvoke(Command(resume="approved"), config)  # execute → finish
    plan = [s.title for s in store.plan.steps] if store.plan is not None else []
    return ReplayTimeline(
        status=str(final["status"]),
        plan=plan,
        transcript=list(final["transcript"]),
        events=events.types,
    )


def _replay(case: ReplayCase) -> ReplayTimeline:
    return asyncio.run(_drive(case))


def _load_cases() -> list[ReplayCase]:
    return [
        ReplayCase.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(_FIXTURES.glob("*.json"))
    ]


def test_golden_runs_replay_deterministically() -> None:
    cases = _load_cases()
    assert cases, "no golden replay fixtures found"
    suite = AgentReplayEvalSuite(cases=cases, replay=_replay)
    outcome = suite.run()
    assert outcome.passed, outcome.failures
    assert outcome.metrics["determinism_rate"] == 1.0
    assert outcome.metrics["golden_match_rate"] == 1.0
