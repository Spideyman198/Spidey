"""Agent-task + groundedness metrics and suites (LLM-free)."""

from __future__ import annotations

from spidey.evaluation.application import AgentTaskEvalSuite, GroundednessEvalSuite
from spidey.evaluation.domain import (
    AgentTaskResult,
    GroundednessClaim,
    Tier,
    groundedness_rate,
    mean_cost_usd,
    success_rate,
)


def _results() -> list[AgentTaskResult]:
    return [
        AgentTaskResult(task_id="t1", succeeded=True, cost_usd=0.20),
        AgentTaskResult(task_id="t2", succeeded=True, cost_usd=0.40),
        AgentTaskResult(task_id="t3", succeeded=False, cost_usd=0.30),
    ]


class TestMetrics:
    def test_success_rate_and_mean_cost(self) -> None:
        results = _results()
        assert round(success_rate(results), 4) == 0.6667
        assert round(mean_cost_usd(results), 4) == 0.3

    def test_empty_is_zero(self) -> None:
        assert success_rate([]) == 0.0
        assert mean_cost_usd([]) == 0.0

    def test_groundedness_rate(self) -> None:
        claims = [
            GroundednessClaim(claim_id="c1", supported=True),
            GroundednessClaim(claim_id="c2", supported=False),
        ]
        assert groundedness_rate(claims) == 0.5
        assert groundedness_rate([]) == 1.0  # no claims → vacuously grounded


class TestAgentTaskSuite:
    def test_reports_success_rate_and_lists_failures(self) -> None:
        suite = AgentTaskEvalSuite(results=_results())
        outcome = suite.run()
        assert outcome.passed  # metric floor is enforced by the blessed baseline
        assert outcome.metrics["success_rate"] == 0.6667
        assert outcome.failures == ["task failed: t3"]
        assert suite.tier is Tier.T2

    def test_empty_suite_passes(self) -> None:
        assert AgentTaskEvalSuite(results=[]).run().passed


class TestGroundednessSuite:
    def test_reports_rate_and_unsupported_claims(self) -> None:
        suite = GroundednessEvalSuite(
            claims=[
                GroundednessClaim(claim_id="c1", supported=True),
                GroundednessClaim(claim_id="c2", supported=False),
            ]
        )
        outcome = suite.run()
        assert outcome.metrics["groundedness_rate"] == 0.5
        assert outcome.failures == ["unsupported claim: c2"]
