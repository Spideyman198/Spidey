"""TerminalService — admit a command, run it sandboxed, scrub what comes back.

This is the application-side choke point for command execution: it is the only
way a command reaches the :class:`Sandbox`, and it never lets one through that
:class:`CommandPolicy` did not admit. Output is treated as hostile (it was
produced by untrusted code): it is size-capped by the sandbox and secret-scanned
here (B4r) before it can enter a prompt, an event, or the UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from spidey.execution.domain import (
    Admission,
    CommandPolicy,
    ExecutionRequest,
    ExecutionResult,
    SandboxLimits,
    scrub_env,
)
from spidey.platform.security import scrub_text

if TYPE_CHECKING:
    from spidey.execution.domain import CommandDecision, Sandbox


class TerminalOutcome(BaseModel):
    """What the caller sees: either a refusal (with the policy reason) or a
    completed, scrubbed execution result."""

    model_config = ConfigDict(frozen=True)

    admitted: bool
    decision_reason: str
    network: str = "none"  # the admitted network posture (none | egress_proxy)
    result: ExecutionResult | None = None


class TerminalService:
    def __init__(self, *, sandbox: Sandbox, policy: CommandPolicy | None = None) -> None:
        self._sandbox = sandbox
        self._policy = policy or CommandPolicy()

    async def run(
        self,
        *,
        argv: list[str],
        workspace_path: str,
        env: dict[str, str] | None = None,
        limits: SandboxLimits | None = None,
        approved: bool = False,
    ) -> TerminalOutcome:
        """Admit and run one command. ``approved`` records that a human already
        authorized an off-list or network command for this call — the policy
        decision still selects the network posture, but an admitted-with-approval
        command runs; a denied (malformed/shell) command never runs, approval or
        not."""
        decision = self._policy.evaluate(argv)
        if not self._is_runnable(decision, approved=approved):
            return TerminalOutcome(
                admitted=False,
                decision_reason=decision.reason,
                network=decision.network.value,
            )

        request = ExecutionRequest(
            argv=argv,
            workspace_path=workspace_path,
            env=scrub_env(env or {}),
            limits=(limits or SandboxLimits()).model_copy(update={"network": decision.network}),
        )
        result = await self._sandbox.run(request)
        return TerminalOutcome(
            admitted=True,
            decision_reason=decision.reason,
            network=decision.network.value,
            result=_scrub_result(result),
        )

    @staticmethod
    def _is_runnable(decision: CommandDecision, *, approved: bool) -> bool:
        if decision.admission is Admission.ALLOWED:
            return True
        # A human can authorize an off-list/network command, but never a DENIED
        # one — a shell-injection attempt is unrunnable as written, full stop.
        return decision.admission is Admission.NEEDS_APPROVAL and approved


def _scrub_result(result: ExecutionResult) -> ExecutionResult:
    """B4r: redact secret shapes from captured output before it leaves the
    boundary. The sandbox already size-capped it; we never un-truncate."""
    return result.model_copy(
        update={"stdout": scrub_text(result.stdout), "stderr": scrub_text(result.stderr)}
    )
