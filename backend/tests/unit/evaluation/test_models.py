"""Domain contracts: cumulative tiers, immutable results."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from spidey.evaluation.domain import EvalReport, SuiteResult, Tier


class TestTierCumulation:
    def test_ranks_are_ordered(self) -> None:
        assert Tier.T1.rank < Tier.T2.rank < Tier.T3.rank

    def test_higher_tier_includes_lower(self) -> None:
        assert Tier.T2.includes(Tier.T1)
        assert Tier.T3.includes(Tier.T1)
        assert Tier.T3.includes(Tier.T3)

    def test_lower_tier_excludes_higher(self) -> None:
        assert not Tier.T1.includes(Tier.T2)
        assert not Tier.T2.includes(Tier.T3)


class TestEvalReport:
    def _result(self, name: str, *, passed: bool) -> SuiteResult:
        return SuiteResult(suite=name, tier=Tier.T1, passed=passed, duration_seconds=0.1)

    def test_passed_requires_all_suites(self) -> None:
        now = datetime.now(tz=UTC)
        report = EvalReport(
            tier=Tier.T1,
            started_at=now,
            finished_at=now,
            results=[self._result("a", passed=True), self._result("b", passed=False)],
        )
        assert not report.passed
        assert report.suite_names == ["a", "b"]

    def test_empty_report_passes(self) -> None:
        now = datetime.now(tz=UTC)
        assert EvalReport(tier=Tier.T1, started_at=now, finished_at=now).passed

    def test_results_are_frozen(self) -> None:
        result = self._result("a", passed=True)
        with pytest.raises(Exception, match="frozen"):
            result.passed = False  # pyright: ignore[reportAttributeAccessIssue]
