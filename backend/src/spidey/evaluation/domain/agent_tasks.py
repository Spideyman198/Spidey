"""Agent-task and groundedness metrics (M10, docs/10).

Pure, order-independent scoring over the results of running the agent on a
curated task set (execution-graded: did the change make the repo's tests pass?)
and over a groundedness check (are the agent's claims supported by retrieved
context, not invented?). The functions take already-produced results, so the
whole metric surface is unit-testable with no model, sandbox, or repository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Sequence


class AgentTaskResult(BaseModel):
    """The outcome of the agent attempting one curated task."""

    model_config = ConfigDict(frozen=True)

    task_id: str
    succeeded: bool  # execution-graded (the task's tests passed)
    cost_usd: float = 0.0


class GroundednessClaim(BaseModel):
    """One claim the agent made and whether retrieved context supports it."""

    model_config = ConfigDict(frozen=True)

    claim_id: str
    supported: bool


def success_rate(results: Sequence[AgentTaskResult]) -> float:
    """Fraction of tasks the agent completed successfully."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.succeeded) / len(results)


def mean_cost_usd(results: Sequence[AgentTaskResult]) -> float:
    """Mean model cost per task (a runaway agent is a failure mode too)."""
    if not results:
        return 0.0
    return sum(r.cost_usd for r in results) / len(results)


def groundedness_rate(claims: Sequence[GroundednessClaim]) -> float:
    """Fraction of claims supported by retrieved context; 1.0 when none made."""
    if not claims:
        return 1.0
    return sum(1 for c in claims if c.supported) / len(claims)
