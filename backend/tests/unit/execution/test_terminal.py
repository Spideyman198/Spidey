"""TerminalService: admission enforced, output scrubbed, approval semantics."""

from __future__ import annotations

from spidey.execution.application import TerminalService
from spidey.execution.domain import ExecutionRequest, ExecutionResult, NetworkPolicy


class FakeSandbox:
    def __init__(self, result: ExecutionResult | None = None) -> None:
        self.result = result or ExecutionResult(exit_code=0, stdout="ok")
        self.requests: list[ExecutionRequest] = []

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        self.requests.append(request)
        return self.result


async def test_allow_listed_command_runs_and_returns_result() -> None:
    sandbox = FakeSandbox(ExecutionResult(exit_code=0, stdout="2 passed"))
    outcome = await TerminalService(sandbox=sandbox).run(
        argv=["pytest", "-q"], workspace_path="/ws"
    )
    assert outcome.admitted
    assert outcome.result is not None
    assert outcome.result.ok
    assert sandbox.requests[0].limits.network is NetworkPolicy.NONE


async def test_denied_shell_attempt_never_reaches_the_sandbox() -> None:
    sandbox = FakeSandbox()
    outcome = await TerminalService(sandbox=sandbox).run(
        argv=["pytest; rm -rf /"], workspace_path="/ws"
    )
    assert not outcome.admitted
    assert outcome.result is None
    assert sandbox.requests == []  # nothing ran


async def test_offlist_command_blocked_without_approval() -> None:
    sandbox = FakeSandbox()
    outcome = await TerminalService(sandbox=sandbox).run(
        argv=["curl", "http://evil"], workspace_path="/ws"
    )
    assert not outcome.admitted
    assert sandbox.requests == []


async def test_offlist_command_runs_with_human_approval() -> None:
    sandbox = FakeSandbox()
    outcome = await TerminalService(sandbox=sandbox).run(
        argv=["rm", "build/"], workspace_path="/ws", approved=True
    )
    assert outcome.admitted
    assert len(sandbox.requests) == 1


async def test_denied_command_cannot_be_forced_by_approval() -> None:
    # A shell-injection attempt is unrunnable as written — approval cannot save it.
    sandbox = FakeSandbox()
    outcome = await TerminalService(sandbox=sandbox).run(
        argv=["a && b"], workspace_path="/ws", approved=True
    )
    assert not outcome.admitted
    assert sandbox.requests == []


async def test_network_command_gets_egress_posture_when_approved() -> None:
    sandbox = FakeSandbox()
    await TerminalService(sandbox=sandbox).run(
        argv=["npm", "install"], workspace_path="/ws", approved=True
    )
    assert sandbox.requests[0].limits.network is NetworkPolicy.EGRESS_PROXY


async def test_secret_in_output_is_scrubbed_before_returning() -> None:
    leaky = ExecutionResult(exit_code=0, stdout="token=sk-ant-abcdefghij0123456789 done", stderr="")
    outcome = await TerminalService(sandbox=FakeSandbox(leaky)).run(
        argv=["pytest"], workspace_path="/ws"
    )
    assert outcome.result is not None
    assert "sk-ant-" not in outcome.result.stdout
    assert "[REDACTED]" in outcome.result.stdout


async def test_env_is_scrubbed_before_reaching_sandbox() -> None:
    sandbox = FakeSandbox()
    await TerminalService(sandbox=sandbox).run(
        argv=["pytest"],
        workspace_path="/ws",
        env={"ANTHROPIC_API_KEY": "secret", "TERM": "xterm"},
    )
    passed_env = sandbox.requests[0].env
    assert "ANTHROPIC_API_KEY" not in passed_env
    assert passed_env["TERM"] == "xterm"
    assert passed_env["PATH"] == "/usr/local/bin:/usr/bin:/bin"
