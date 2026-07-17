"""M8 exit criteria, offline: (1) a scoped change lands on the run's isolated
branch through the full coder → approval gate → apply → review → commit flow;
(2) a planted bad edit is caught by the reviewer and repaired by the coder's
second pass. Real git repo, real GuardedFileSystem, real ToolRegistry + edit
tool — only the model responses are scripted (ADR-0009)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from git import Repo
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from spidey.agents.application import ToolRegistry
from spidey.agents.domain.runs import Approval, ApprovalStatus, Plan, RunStatus
from spidey.agents.graph import GraphNodes, build_run_graph, initial_state
from spidey.agents.infrastructure import CodeEditProvider
from spidey.agents.infrastructure.code_edit import EDIT_TOOL
from spidey.llm.domain import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FinishReason,
    MessageRole,
    Role,
    ToolCall,
    Usage,
)
from spidey.workspaces.application import GitWorkflowService, branch_for_run
from spidey.workspaces.infrastructure.filesystem import GuardedFileSystem
from spidey.workspaces.infrastructure.git_provider import GitPythonProvider

if TYPE_CHECKING:
    from spidey.agents.domain.runs import RunBudget


class _Settings:
    allowed_git_hosts: ClassVar[list[str]] = ["github.com"]


class _Storage:
    """WorkspaceStorage surface the workflow + edit tool need, on one root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def path_for(self, workspace_id: uuid.UUID) -> str:
        return str(self._root)

    def filesystem(self, workspace_id: uuid.UUID) -> GuardedFileSystem:
        return GuardedFileSystem(self._root)


def _text(content: str) -> ChatResponse:
    return ChatResponse(
        message=ChatMessage(role=MessageRole.ASSISTANT, content=content),
        finish_reason=FinishReason.STOP,
        usage=Usage(prompt_tokens=5, completion_tokens=3),
        provider="scripted",
        model="m",
    )


def _edit_call(old: str, new: str, *, path: str = "app.py") -> ChatResponse:
    call = ToolCall(
        id=f"call_{uuid.uuid4().hex[:8]}",
        name=EDIT_TOOL,
        arguments={"path": path, "old_string": old, "new_string": new},
    )
    return ChatResponse(
        message=ChatMessage(role=MessageRole.ASSISTANT, content="", tool_calls=[call]),
        finish_reason=FinishReason.TOOL_USE,
        usage=Usage(prompt_tokens=5, completion_tokens=3),
        provider="scripted",
        model="m",
    )


class ScriptedGateway:
    """Pops a scripted response per role; records coder prompts for assertions."""

    def __init__(self, *, plan: str, coder: list[ChatResponse], reviewer: list[str]) -> None:
        self._plan = plan
        self._coder = list(coder)
        self._reviewer = list(reviewer)
        self.coder_prompts: list[str] = []

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
            return _text(self._plan)
        if role is Role.REVIEWER:
            return _text(self._reviewer.pop(0))
        self.coder_prompts.append(request.messages[-1].content)
        return self._coder.pop(0)


class WorkflowStore:
    """In-memory RunStore rich enough for the approval workflow."""

    def __init__(self) -> None:
        self.plan: Plan | None = None
        self.statuses: list[RunStatus] = []
        self.approvals: dict[uuid.UUID, Approval] = {}
        self.base_commit: str | None = None

    async def save_plan(self, *, run_id: uuid.UUID, plan: Plan) -> None:
        self.plan = plan

    async def get_plan(self, run_id: uuid.UUID) -> Plan | None:
        return self.plan

    async def set_status(
        self, *, run_id: uuid.UUID, status: RunStatus, error: str | None = None
    ) -> None:
        self.statuses.append(status)

    async def set_base_commit(self, *, run_id: uuid.UUID, base_commit: str | None) -> None:
        self.base_commit = base_commit

    async def get_budget(self, run_id: uuid.UUID) -> RunBudget | None:
        return None

    async def set_budget(self, *, run_id: uuid.UUID, budget: object) -> None: ...

    async def create_approval(self, approval: Approval) -> None:
        self.approvals[approval.id] = approval

    async def get_approval(self, approval_id: uuid.UUID) -> Approval | None:
        return self.approvals.get(approval_id)

    def approve_all(self, decided_by: uuid.UUID) -> None:
        """The human grants every pending approval (the API path in production)."""
        for key, approval in self.approvals.items():
            if approval.status is ApprovalStatus.PENDING:
                self.approvals[key] = approval.model_copy(
                    update={
                        "status": ApprovalStatus.APPROVED,
                        "decided_by": decided_by,
                        "decided_at": datetime.now(tz=UTC),
                    }
                )


class FakeEvents:
    def __init__(self) -> None:
        self.types: list[str] = []
        self.payloads: list[dict[str, object]] = []

    def add(self, envelope: object) -> None:
        self.types.append(envelope.event_type)  # type: ignore[attr-defined]
        self.payloads.append(envelope.payload)  # type: ignore[attr-defined]


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    return root


def _harness(
    tmp_path: Path, gateway: ScriptedGateway
) -> tuple[object, WorkflowStore, FakeEvents, Path, dict[str, object]]:
    root = _workspace(tmp_path)
    storage = _Storage(root)
    store, events = WorkflowStore(), FakeEvents()
    nodes = GraphNodes(
        gateway=gateway,  # type: ignore[arg-type]
        registry=ToolRegistry(providers=[CodeEditProvider(storage=storage)]),  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        events=events,  # type: ignore[arg-type]
        git=GitWorkflowService(
            git=GitPythonProvider(_Settings()),  # type: ignore[arg-type]
            storage=storage,  # type: ignore[arg-type]
        ),
    )
    graph = build_run_graph(nodes, checkpointer=MemorySaver())
    run_id = uuid.uuid4()
    config: dict[str, object] = {"configurable": {"thread_id": str(run_id)}}
    state = initial_state(
        run_id=str(run_id),
        owner_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        goal="update the return value",
    )
    return graph, store, events, root, {"config": config, "state": state, "run_id": run_id}


async def test_scoped_change_lands_on_isolated_run_branch(tmp_path: Path) -> None:
    """Exit criterion 1: goal → plan → approval → edit (human-gated) → review →
    atomic conventional commit on spidey/run-<id>."""
    gateway = ScriptedGateway(
        plan="change the return value to 2",
        coder=[_edit_call("return 1", "return 2"), _text("proposed the fix")],
        reviewer=["APPROVE"],
    )
    graph, store, events, root, h = _harness(tmp_path, gateway)
    config, state, run_id = h["config"], h["state"], h["run_id"]
    owner = uuid.UUID(state["owner_id"])  # type: ignore[index]

    # Plan pause → human approves the plan.
    await graph.ainvoke(state, config)  # type: ignore[attr-defined]
    result = await graph.ainvoke(Command(resume="approved"), config)  # type: ignore[attr-defined]

    # Edit pause: the proposal is parked behind a recorded approval.
    assert "__interrupt__" in result
    assert RunStatus.AWAITING_APPROVAL in store.statuses
    pending = [a for a in store.approvals.values() if a.status is ApprovalStatus.PENDING]
    assert len(pending) == 1
    assert pending[0].tool == EDIT_TOOL
    # Nothing was written while awaiting the human.
    assert "return 1" in (root / "app.py").read_text(encoding="utf-8")

    # Human approves the edit → apply → review (APPROVE) → commit → complete.
    store.approve_all(owner)
    final = await graph.ainvoke(Command(resume="approved"), config)  # type: ignore[attr-defined]

    assert final["status"] == RunStatus.COMPLETED.value
    assert "return 2" in (root / "app.py").read_text(encoding="utf-8")
    repo = Repo(root)
    try:
        assert repo.active_branch.name == branch_for_run(run_id)  # type: ignore[arg-type]
        message = str(repo.head.commit.message)
        assert message.startswith("feat(run):")
        assert store.base_commit is not None
        assert repo.head.commit.hexsha != store.base_commit  # a step landed
    finally:
        repo.close()
    for expected in (
        "agents.approval_requested",
        "agents.code_generated",
        "agents.review_completed",
        "agents.step_committed",
        "chat.run_completed",
    ):
        assert expected in events.types, expected


async def test_planted_bad_edit_is_caught_and_repaired(tmp_path: Path) -> None:
    """Exit criterion 2: the reviewer rejects a bad edit; the coder's second
    pass (fed the critique) repairs it; the repaired change is what commits."""
    gateway = ScriptedGateway(
        plan="change the return value to 3",
        coder=[
            _edit_call("return 1", "return 99"),  # planted bad edit
            _text("changed it"),
            _edit_call("return 99", "return 3"),  # repair after critique
            _text("fixed per review"),
        ],
        reviewer=["The step requires return 3, not 99. Change it.", "APPROVE"],
    )
    graph, store, events, root, h = _harness(tmp_path, gateway)
    config, state = h["config"], h["state"]
    owner = uuid.UUID(state["owner_id"])  # type: ignore[index]

    await graph.ainvoke(state, config)  # type: ignore[attr-defined]
    await graph.ainvoke(Command(resume="approved"), config)  # type: ignore[attr-defined]

    # Approve the bad edit; the reviewer catches it and loops the coder, which
    # proposes the repair — parking at a second approval gate.
    store.approve_all(owner)
    mid = await graph.ainvoke(Command(resume="approved"), config)  # type: ignore[attr-defined]
    assert "__interrupt__" in mid
    assert "return 99" in (root / "app.py").read_text(encoding="utf-8")
    # The critique reached the coder's second prompt.
    assert any("not 99" in p for p in gateway.coder_prompts)

    # Approve the repair → second review approves → commit → complete.
    store.approve_all(owner)
    final = await graph.ainvoke(Command(resume="approved"), config)  # type: ignore[attr-defined]

    assert final["status"] == RunStatus.COMPLETED.value
    assert "return 3" in (root / "app.py").read_text(encoding="utf-8")
    assert "return 99" not in (root / "app.py").read_text(encoding="utf-8")

    verdicts = [
        p["verdict"]
        for p in events.payloads
        if p.get("verdict")  # ReviewCompleted only
    ]
    assert verdicts == ["changes_requested", "approved"]
    assert "agents.step_committed" in events.types
    repo = Repo(root)
    try:
        # One atomic commit containing the net, repaired change.
        diff = repo.git.show("HEAD", format="", no_color=True)
        assert "+    return 3" in diff
        assert "return 99" not in diff
    finally:
        repo.close()
