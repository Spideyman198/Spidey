"""TesterService — detect the project's test framework, run it sandboxed, and
return a structured verdict.

Framework detection is driven by the *marker files present at the workspace
root*, which the caller supplies (it holds the SafeFileSystem; this context does
no file I/O). Detection picks a fixed, allow-listed command — never anything
derived from repo content — so a hostile repo cannot influence what runs, only
what that fixed runner then reports. The run itself goes through the same
:class:`TerminalService` admission + sandbox path as any command.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from spidey.execution.domain import ExecutionResult, SandboxLimits

if TYPE_CHECKING:
    from spidey.execution.application.terminal import TerminalService


class TestFramework(StrEnum):
    PYTEST = "pytest"
    NPM = "npm"
    GO = "go"
    CARGO = "cargo"
    UNKNOWN = "unknown"


# Not a pytest test class despite the ``Test`` prefix (set after creation so it
# is not misread as an enum member).
TestFramework.__test__ = False  # type: ignore[attr-defined]


# Root marker file → framework. First match wins in the fixed order below, so a
# polyglot repo resolves deterministically (not by repo-controlled ordering).
_MARKERS: tuple[tuple[str, TestFramework], ...] = (
    ("pyproject.toml", TestFramework.PYTEST),
    ("pytest.ini", TestFramework.PYTEST),
    ("tox.ini", TestFramework.PYTEST),
    ("setup.cfg", TestFramework.PYTEST),
    ("go.mod", TestFramework.GO),
    ("Cargo.toml", TestFramework.CARGO),
    ("package.json", TestFramework.NPM),
)

# The root filenames a caller must probe to let detection work (it does no I/O).
MARKER_FILES: frozenset[str] = frozenset(marker for marker, _ in _MARKERS)

# Framework → the fixed, allow-listed, offline test command.
_COMMANDS: dict[TestFramework, list[str]] = {
    TestFramework.PYTEST: ["pytest", "-q", "--no-header"],
    TestFramework.NPM: ["npm", "test", "--", "--watch=false"],
    TestFramework.GO: ["go", "test", "./..."],
    TestFramework.CARGO: ["cargo", "test"],
}


class TestReport(BaseModel):
    """Structured result of a test run — the Tester agent's output contract."""

    __test__ = False  # not a pytest test class despite the ``Test`` prefix

    model_config = ConfigDict(frozen=True)

    framework: TestFramework
    ran: bool  # False when no framework was detected or the command was refused
    passed: bool
    exit_code: int | None = None
    passed_count: int | None = None
    failed_count: int | None = None
    timed_out: bool = False
    summary: str = ""


def detect_framework(root_files: frozenset[str]) -> TestFramework:
    """Pick the test framework from the workspace's root marker files."""
    for marker, framework in _MARKERS:
        if marker in root_files:
            return framework
    return TestFramework.UNKNOWN


class TesterService:
    __test__ = False  # not a pytest test class despite the ``Tester`` prefix

    def __init__(self, *, terminal: TerminalService) -> None:
        self._terminal = terminal

    async def run(
        self,
        *,
        workspace_path: str,
        root_files: frozenset[str],
        limits: SandboxLimits | None = None,
    ) -> TestReport:
        framework = detect_framework(root_files)
        if framework is TestFramework.UNKNOWN:
            return TestReport(
                framework=framework,
                ran=False,
                passed=False,
                summary="no recognized test framework at the workspace root",
            )
        outcome = await self._terminal.run(
            argv=_COMMANDS[framework],
            workspace_path=workspace_path,
            limits=limits or SandboxLimits(),
        )
        if not outcome.admitted or outcome.result is None:
            return TestReport(
                framework=framework,
                ran=False,
                passed=False,
                summary=f"test command not admitted: {outcome.decision_reason}",
            )
        return _to_report(framework, outcome.result)


def _to_report(framework: TestFramework, result: ExecutionResult) -> TestReport:
    passed_count, failed_count = (
        _parse_pytest(result.stdout) if framework is TestFramework.PYTEST else (None, None)
    )
    passed = result.exit_code == 0 and not result.timed_out
    tail = (result.stdout or result.stderr).strip().splitlines()[-1:] or [""]
    return TestReport(
        framework=framework,
        ran=True,
        passed=passed,
        exit_code=result.exit_code,
        passed_count=passed_count,
        failed_count=failed_count,
        timed_out=result.timed_out,
        summary=tail[0][:300],
    )


def _parse_pytest(stdout: str) -> tuple[int | None, int | None]:
    """Pull passed/failed counts from pytest's summary line, if present."""
    passed = failed = None
    for match in re.finditer(r"(\d+) (passed|failed)", stdout):
        count, kind = int(match.group(1)), match.group(2)
        if kind == "passed":
            passed = count
        else:
            failed = count
    return passed, failed
