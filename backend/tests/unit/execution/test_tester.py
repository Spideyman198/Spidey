"""TesterService: framework detection from root markers, structured verdicts."""

from __future__ import annotations

from spidey.execution.application import (
    TerminalService,
    TesterService,
    TestFramework,
    detect_framework,
)
from spidey.execution.domain import ExecutionRequest, ExecutionResult


class FakeSandbox:
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result
        self.requests: list[ExecutionRequest] = []

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        return self.result


def _tester(result: ExecutionResult) -> tuple[TesterService, FakeSandbox]:
    sandbox = FakeSandbox(result)
    terminal = TerminalService(sandbox=sandbox)
    return TesterService(terminal=terminal), sandbox


class TestDetection:
    def test_python_project_detected_as_pytest(self) -> None:
        assert detect_framework(frozenset({"pyproject.toml", "src"})) is TestFramework.PYTEST

    def test_go_and_cargo_and_npm(self) -> None:
        assert detect_framework(frozenset({"go.mod"})) is TestFramework.GO
        assert detect_framework(frozenset({"Cargo.toml"})) is TestFramework.CARGO
        assert detect_framework(frozenset({"package.json"})) is TestFramework.NPM

    def test_polyglot_resolves_deterministically(self) -> None:
        # Python marker wins by the fixed order, not repo-controlled ordering.
        both = frozenset({"package.json", "pyproject.toml"})
        assert detect_framework(both) is TestFramework.PYTEST

    def test_no_marker_is_unknown(self) -> None:
        assert detect_framework(frozenset({"README.md"})) is TestFramework.UNKNOWN


class TestRun:
    async def test_unknown_framework_does_not_run(self) -> None:
        tester, sandbox = _tester(ExecutionResult(exit_code=0))
        report = await tester.run(workspace_path="/ws", root_files=frozenset({"README.md"}))
        assert not report.ran
        assert not report.passed
        assert sandbox.requests == []

    async def test_passing_pytest_run_parses_counts(self) -> None:
        tester, sandbox = _tester(ExecutionResult(exit_code=0, stdout="5 passed in 0.10s"))
        report = await tester.run(workspace_path="/ws", root_files=frozenset({"pyproject.toml"}))
        assert report.ran
        assert report.passed
        assert report.passed_count == 5
        assert report.failed_count is None
        assert sandbox.requests[0].argv[0] == "pytest"

    async def test_failing_pytest_run_is_not_passed(self) -> None:
        tester, _ = _tester(ExecutionResult(exit_code=1, stdout="3 passed, 2 failed in 0.2s"))
        report = await tester.run(workspace_path="/ws", root_files=frozenset({"pytest.ini"}))
        assert not report.passed
        assert report.passed_count == 3
        assert report.failed_count == 2

    async def test_timeout_is_surfaced_as_not_passed(self) -> None:
        tester, _ = _tester(ExecutionResult(exit_code=None, timed_out=True))
        report = await tester.run(workspace_path="/ws", root_files=frozenset({"go.mod"}))
        assert report.ran
        assert not report.passed
        assert report.timed_out
