"""Agent-task and groundedness eval suites (T2, M10, docs/10 §4).

Both grade already-produced results, so the same suite runs offline in a unit
test or against a live agent run. ``AgentTaskEvalSuite`` reports the agent's
success rate and mean cost over a curated task set — the first success-rate
baseline the milestone commits. ``GroundednessEvalSuite`` reports the fraction
of the agent's claims supported by retrieved context. Metric floors are enforced
separately by the blessed baselines (``evaluation/baselines/``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.evaluation.domain import SuiteOutcome, Tier
from spidey.evaluation.domain.agent_tasks import (
    groundedness_rate,
    mean_cost_usd,
    success_rate,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spidey.evaluation.domain.agent_tasks import AgentTaskResult, GroundednessClaim


class AgentTaskEvalSuite:
    """Grades the agent over curated tasks; satisfies the ``EvalSuite`` port."""

    def __init__(
        self,
        *,
        results: Sequence[AgentTaskResult],
        name: str = "agent_tasks",
        tier: Tier = Tier.T2,
    ) -> None:
        self._results = list(results)
        self._name = name
        self._tier = tier

    @property
    def name(self) -> str:
        return self._name

    @property
    def tier(self) -> Tier:
        return self._tier

    def run(self) -> SuiteOutcome:
        if not self._results:
            return SuiteOutcome(passed=True, metrics={}, failures=[])
        failures = [f"task failed: {r.task_id}" for r in self._results if not r.succeeded]
        metrics = {
            "success_rate": round(success_rate(self._results), 4),
            "mean_cost_usd": round(mean_cost_usd(self._results), 4),
        }
        # Individual task failures are informational; the success-rate *floor* is
        # enforced by the blessed baseline, so the suite itself passes when it ran.
        return SuiteOutcome(passed=True, metrics=metrics, failures=failures)


class GroundednessEvalSuite:
    """Grades whether the agent's claims are supported by retrieved context."""

    def __init__(
        self,
        *,
        claims: Sequence[GroundednessClaim],
        name: str = "groundedness",
        tier: Tier = Tier.T2,
    ) -> None:
        self._claims = list(claims)
        self._name = name
        self._tier = tier

    @property
    def name(self) -> str:
        return self._name

    @property
    def tier(self) -> Tier:
        return self._tier

    def run(self) -> SuiteOutcome:
        rate = groundedness_rate(self._claims)
        failures = [f"unsupported claim: {c.claim_id}" for c in self._claims if not c.supported]
        return SuiteOutcome(
            passed=True, metrics={"groundedness_rate": round(rate, 4)}, failures=failures
        )
