"""M10 exit criterion: fix → tests → approval → PR, end to end and offline.

Drives the real graph with a fixture gateway, a stateful tester tool that fails
once (triggering the debugger's bounded fix loop) then passes, a fake git
workflow, and a fake PR service. Proves: failing tests route to the debugger, a
fix step is appended and re-tested, and — only past the human PR gate — a pull
request is opened before the run completes.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from spidey.agents.application import ToolRegistry
from spidey.agents.domain.tools import SideEffect, ToolResult, ToolSpec, TrustTier
from spidey.agents.graph import GraphNodes, build_run_graph, initial_state
from spidey.identity.domain.models import Role as IdentityRole
from spidey.llm.domain import (
    ChatMessage,
    ChatResponse,
    FinishReason,
    MessageRole,
    Role,
    Usage,
)
from spidey.workspaces.application import RunBranch
from spidey.workspaces.domain.ports import PullRequest

if TYPE_CHECKING:
    from spidey.agents.domain.runs import Plan, RunBudget, RunStatus
    from spidey.agents.domain.tools import ToolContext
    from spidey.llm.domain import ChatRequest


class _Gateway:
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
        text = {
            Role.PLANNER: "apply the change",
            Role.DEBUGGER: "the return value is wrong; fix it",
            Role.DOCUMENTER: "Corrects the return value; tests pass.",
        }.get(role, "done")
        return ChatResponse(
            message=ChatMessage(role=MessageRole.ASSISTANT, content=text),
            finish_reason=FinishReason.STOP,
            usage=Usage(prompt_tokens=5, completion_tokens=3),
            provider="fixture",
            model="m",
        )


class _TesterProvider:
    """A native-shaped tester tool: FAILS the first run, PASSES afterwards."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def namespace(self) -> str:
        return "execution"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="tester.run",
                description="run tests",
                side_effect=SideEffect.READ,
                trust_tier=TrustTier.TRUSTED,
                required_role=IdentityRole.DEVELOPER,
            )
        ]

    async def invoke(
        self, name: str, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        self.calls += 1
        passed = self.calls > 1
        return ToolResult.success(
            json.dumps({"framework": "pytest", "ran": True, "passed": passed})
        )


class _Store:
    def __init__(self) -> None:
        self.plan: Plan | None = None
        self.statuses: list[str] = []

    async def save_plan(self, *, run_id: uuid.UUID, plan: Plan) -> None:
        self.plan = plan

    async def get_plan(self, run_id: uuid.UUID) -> Plan | None:
        return self.plan

    async def set_status(
        self, *, run_id: uuid.UUID, status: RunStatus, error: str | None = None
    ) -> None:
        self.statuses.append(status.value)

    async def get_budget(self, run_id: uuid.UUID) -> RunBudget | None:
        return None

    async def set_budget(self, *, run_id: uuid.UUID, budget: RunBudget) -> None: ...
    async def set_base_commit(self, *, run_id: uuid.UUID, base_commit: str | None) -> None: ...


class _Git:
    async def prepare_run_branch(self, *, workspace_id: uuid.UUID, run_id: uuid.UUID) -> RunBranch:
        return RunBranch(branch=f"spidey/run-{run_id}", base_commit="base0")

    async def run_diff(self, *, workspace_id: uuid.UUID, base: str | None) -> str:
        return "diff --git a/x b/x"


class _Pr:
    def __init__(self) -> None:
        self.delivered = 0

    async def deliver(
        self, *, workspace_id: uuid.UUID, branch: str, title: str, body: str
    ) -> PullRequest:
        self.delivered += 1
        return PullRequest(number=42, url="https://github.com/o/r/pull/42")


class _Events:
    def __init__(self) -> None:
        self.types: list[str] = []

    def add(self, envelope: object) -> None:
        self.types.append(envelope.event_type)  # type: ignore[attr-defined]


async def _drive() -> tuple[dict[str, object], _Gateway, _TesterProvider, _Pr, _Events]:
    gateway, tester, pr, events = _Gateway(), _TesterProvider(), _Pr(), _Events()
    nodes = GraphNodes(
        gateway=gateway,  # type: ignore[arg-type]
        registry=ToolRegistry(providers=[tester]),
        store=_Store(),  # type: ignore[arg-type]
        events=events,  # type: ignore[arg-type]
        git=_Git(),  # type: ignore[arg-type]
        pr=pr,  # type: ignore[arg-type]
    )
    graph = build_run_graph(nodes, checkpointer=MemorySaver())
    run_id, owner_id, ws_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    config = {"configurable": {"thread_id": str(run_id)}}
    state = initial_state(
        run_id=str(run_id), owner_id=str(owner_id), workspace_id=str(ws_id), goal="fix it"
    )
    await graph.ainvoke(state, config)  # → pause at plan approval
    await graph.ainvoke(Command(resume="approved"), config)  # → runs to the PR gate
    final = await graph.ainvoke(Command(resume="approved"), config)  # → opens PR, finalizes
    return final, gateway, tester, pr, events


async def test_fix_tests_approval_pr_end_to_end() -> None:
    final, gateway, tester, pr, events = await _drive()

    # Tests failed once, the debugger ran, tests were re-run and passed.
    assert tester.calls == 2
    assert Role.DEBUGGER in gateway.roles
    assert "agents.fix_generated" in events.types

    # Documented, then a PR opened only past the human gate, then completed.
    assert "agents.docs_generated" in events.types
    assert pr.delivered == 1
    assert "agents.pull_request_opened" in events.types
    assert "agents.run_reported" in events.types
    assert final["status"] == "completed"
    assert final["pr_url"] == "https://github.com/o/r/pull/42"
