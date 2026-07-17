"""SandboxToolProvider: tester runs inline (READ), terminal is approval-gated
(WRITE) through the registry, and shell attempts are refused by policy."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spidey.agents.application import ToolRegistry
from spidey.agents.domain import ToolContext, ToolOutcome
from spidey.agents.domain.runs import Approval, ApprovalStatus
from spidey.agents.infrastructure import SandboxToolProvider
from spidey.agents.infrastructure.sandbox_tools import TERMINAL_TOOL, TESTER_TOOL
from spidey.execution.domain import ExecutionRequest, ExecutionResult
from spidey.identity.domain.models import Role

if TYPE_CHECKING:
    from spidey.workspaces.domain.ports import WorkspaceFile


class FakeSandbox:
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result
        self.requests: list[ExecutionRequest] = []

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        return self.result


class FakeFileSystem:
    def __init__(self, files: set[str]) -> None:
        self._files = files

    def is_file(self, path: str) -> bool:
        return path in self._files

    # Unused by these tests but part of the port surface.
    def read_text(self, path: str) -> str: ...  # pragma: no cover
    def walk_files(self) -> list[WorkspaceFile]:  # pragma: no cover
        return []


class FakeStorage:
    def __init__(self, files: set[str]) -> None:
        self._files = files

    def path_for(self, workspace_id: uuid.UUID) -> str:
        return "/var/lib/spidey/ws"

    def filesystem(self, workspace_id: uuid.UUID) -> FakeFileSystem:
        return FakeFileSystem(self._files)


def _context() -> ToolContext:
    return ToolContext(
        actor_user_id=uuid.uuid4(),
        role=Role.DEVELOPER,
        run_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
    )


def _provider(sandbox: FakeSandbox, files: set[str]) -> SandboxToolProvider:
    return SandboxToolProvider(
        sandbox=sandbox,  # type: ignore[arg-type]
        storage=FakeStorage(files),  # type: ignore[arg-type]
    )


class TestTester:
    async def test_runs_detected_framework_and_reports_pass(self) -> None:
        sandbox = FakeSandbox(ExecutionResult(exit_code=0, stdout="4 passed in 0.1s"))
        provider = _provider(sandbox, {"pyproject.toml"})
        result = await provider.invoke(TESTER_TOOL, {}, _context())
        assert result.ok
        report = json.loads(result.content)
        assert report["framework"] == "pytest"
        assert report["passed"] is True
        assert report["passed_count"] == 4
        assert sandbox.requests[0].argv[0] == "pytest"
        # Tester runs with no network.
        assert sandbox.requests[0].limits.network.value == "none"

    async def test_no_framework_does_not_execute(self) -> None:
        sandbox = FakeSandbox(ExecutionResult(exit_code=0))
        provider = _provider(sandbox, {"README.md"})
        result = await provider.invoke(TESTER_TOOL, {}, _context())
        report = json.loads(result.content)
        assert report["ran"] is False
        assert sandbox.requests == []


class TestTerminalThroughRegistry:
    def _registry(self, sandbox: FakeSandbox) -> ToolRegistry:
        return ToolRegistry(providers=[_provider(sandbox, set())])

    def _approval(self, run_id: uuid.UUID | None) -> Approval:
        return Approval(
            id=uuid.uuid4(),
            run_id=run_id or uuid.uuid4(),
            tool=TERMINAL_TOOL,
            side_effect="write",
            arguments_preview="{}",
            status=ApprovalStatus.APPROVED,
            requested_at=datetime.now(tz=UTC),
        )

    async def test_terminal_denied_without_approval(self) -> None:
        sandbox = FakeSandbox(ExecutionResult(exit_code=0))
        registry = self._registry(sandbox)
        result = await registry.invoke(
            name=TERMINAL_TOOL, arguments={"argv": ["pytest"]}, context=_context()
        )
        assert result.outcome is ToolOutcome.DENIED
        assert sandbox.requests == []  # never reached the sandbox

    async def test_terminal_runs_with_matching_approval(self) -> None:
        sandbox = FakeSandbox(ExecutionResult(exit_code=0, stdout="ok"))
        registry = self._registry(sandbox)
        context = _context()
        result = await registry.invoke(
            name=TERMINAL_TOOL,
            arguments={"argv": ["pytest", "-q"]},
            context=context,
            approval=self._approval(context.run_id),
        )
        assert result.ok
        assert json.loads(result.content)["exit_code"] == 0
        assert sandbox.requests[0].argv == ["pytest", "-q"]

    async def test_shell_attempt_refused_even_when_approved(self) -> None:
        sandbox = FakeSandbox(ExecutionResult(exit_code=0))
        registry = self._registry(sandbox)
        context = _context()
        result = await registry.invoke(
            name=TERMINAL_TOOL,
            arguments={"argv": ["pytest; rm -rf /"]},
            context=context,
            approval=self._approval(context.run_id),
        )
        assert result.outcome is ToolOutcome.DENIED
        assert sandbox.requests == []  # CommandPolicy blocked it inside the sandbox path
