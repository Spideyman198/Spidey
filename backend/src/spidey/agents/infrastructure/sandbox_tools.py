"""Native sandbox tools — ``terminal.run`` and ``tester.run`` (M9).

The most dangerous capability is native and served over MCP, never delegated to
an external server (docs/05 §2): the CommandPolicy allow-list and container
hardening are non-negotiable in-process code. Both tools bind to the run's
workspace from the trusted :class:`ToolContext`, never from arguments.

- ``tester.run`` is ``READ``: it runs the *fixed*, allow-listed test command for
  the detected framework, wholly inside the sandbox (network none). The sandbox
  is the containment boundary, so an automated test run needs no per-call human
  gate — a hostile repo can only make its own tests fail, not escape.
- ``terminal.run`` is ``WRITE``: an arbitrary argv. The registry therefore
  denies it without a resolved human approval (M7 invariant); by the time this
  provider runs, a human has authorized the command, so the CommandPolicy admits
  approved off-list/network commands (but still rejects shell-injection).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from spidey.agents.domain.tools import SideEffect, ToolResult, ToolSpec, TrustTier
from spidey.execution.application import (
    MARKER_FILES,
    TerminalService,
    TesterService,
)
from spidey.execution.domain import CommandPolicy
from spidey.identity.domain.models import Role
from spidey.platform.events import CommandExecuted, EventEnvelope, TestsCompleted

if TYPE_CHECKING:
    from spidey.agents.domain.tools import ToolContext
    from spidey.execution.domain import Sandbox
    from spidey.platform.events import EventPublisher
    from spidey.workspaces.domain.ports import WorkspaceStorage

TERMINAL_TOOL = "terminal.run"
TESTER_TOOL = "tester.run"

_MAX_ARGV = 64
_TERMINAL_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "argv": {
            "type": "array",
            "items": {"type": "string", "maxLength": 4096},
            "minItems": 1,
            "maxItems": _MAX_ARGV,
            "description": "Command as an argv array. There is no shell.",
        }
    },
    "required": ["argv"],
    "additionalProperties": False,
}
_TESTER_SCHEMA: dict[str, object] = {"type": "object", "additionalProperties": False}


class SandboxToolProvider:
    """Offers ``terminal.run`` + ``tester.run`` over one hardened sandbox."""

    def __init__(
        self,
        *,
        sandbox: Sandbox,
        storage: WorkspaceStorage,
        events: EventPublisher | None = None,
        allow_network_installs: bool = False,
    ) -> None:
        self._terminal = TerminalService(
            sandbox=sandbox,
            policy=CommandPolicy(allow_network_installs=allow_network_installs),
        )
        self._tester = TesterService(terminal=self._terminal)
        self._storage = storage
        self._events = events

    @property
    def namespace(self) -> str:
        return "execution"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=TESTER_TOOL,
                description=(
                    "Detect the workspace's test framework and run its test "
                    "suite inside a network-isolated sandbox. Returns a "
                    "structured pass/fail report."
                ),
                input_schema=_TESTER_SCHEMA,
                side_effect=SideEffect.READ,
                trust_tier=TrustTier.TRUSTED,
                required_role=Role.DEVELOPER,
                timeout_seconds=180.0,
            ),
            ToolSpec(
                name=TERMINAL_TOOL,
                description=(
                    "Run one command (argv array — no shell) inside a hardened, "
                    "network-isolated sandbox against the workspace. Requires "
                    "human approval; off-allow-list or network commands need it "
                    "explicitly."
                ),
                input_schema=_TERMINAL_SCHEMA,
                side_effect=SideEffect.WRITE,
                trust_tier=TrustTier.TRUSTED,
                required_role=Role.DEVELOPER,
                timeout_seconds=180.0,
            ),
        ]

    async def invoke(
        self, name: str, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        if context.workspace_id is None:
            return ToolResult.unavailable("no workspace is bound to this run")
        workspace_path = self._storage.path_for(context.workspace_id)
        if name == TESTER_TOOL:
            return await self._run_tester(workspace_path, context)
        if name == TERMINAL_TOOL:
            return await self._run_terminal(arguments, workspace_path, context)
        return ToolResult.error(f"unknown tool {name!r}")

    async def _run_tester(self, workspace_path: str, context: ToolContext) -> ToolResult:
        filesystem = self._storage.filesystem(context.workspace_id)  # type: ignore[arg-type]
        root_files = frozenset(m for m in MARKER_FILES if filesystem.is_file(m))
        report = await self._tester.run(workspace_path=workspace_path, root_files=root_files)
        self._emit(
            TestsCompleted(
                framework=report.framework.value,
                passed=report.passed,
                passed_count=report.passed_count,
                failed_count=report.failed_count,
            ),
            context,
        )
        return ToolResult.success(report.model_dump_json())

    async def _run_terminal(
        self, arguments: dict[str, object], workspace_path: str, context: ToolContext
    ) -> ToolResult:
        argv_raw = arguments.get("argv")
        if not isinstance(argv_raw, list):
            return ToolResult.error("'argv' must be an array of strings")
        items = cast("list[object]", argv_raw)
        if not all(isinstance(item, str) for item in items):
            return ToolResult.error("'argv' must be an array of strings")
        argv = [str(item) for item in items]
        # The registry only reaches a WRITE tool once a human approval is
        # resolved, so an admitted command here is already authorized.
        outcome = await self._terminal.run(argv=argv, workspace_path=workspace_path, approved=True)
        result = outcome.result
        self._emit(
            CommandExecuted(
                argv0=argv[0],
                admitted=outcome.admitted,
                exit_code=result.exit_code if result else None,
                timed_out=result.timed_out if result else False,
                network=outcome.network,
            ),
            context,
        )
        if not outcome.admitted:
            return ToolResult.denied(outcome.decision_reason)
        payload = {
            "exit_code": result.exit_code if result else None,
            "timed_out": result.timed_out if result else False,
            "truncated": result.truncated if result else False,
            "stdout": result.stdout if result else "",
            "stderr": result.stderr if result else "",
        }
        return ToolResult.success(json.dumps(payload))

    def _emit(self, payload: CommandExecuted | TestsCompleted, context: ToolContext) -> None:
        if self._events is None:
            return
        self._events.add(
            EventEnvelope.of(
                payload,
                run_id=context.run_id,
                workspace_id=context.workspace_id,
                actor=str(context.actor_user_id),
            )
        )
