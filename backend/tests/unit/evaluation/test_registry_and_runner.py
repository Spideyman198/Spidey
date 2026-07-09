"""Registry selection rules and runner error containment."""

from __future__ import annotations

import pytest

from spidey.evaluation.application import SuiteRegistry, build_default_registry, run_tier
from spidey.evaluation.domain import Tier
from spidey.platform.errors import ConflictError
from tests.unit.evaluation.fakes import FakeSuite


class TestRegistry:
    def test_duplicate_name_rejected(self) -> None:
        registry = SuiteRegistry()
        registry.register(FakeSuite("retrieval"))
        with pytest.raises(ConflictError):
            registry.register(FakeSuite("retrieval"))

    def test_tier_selection_is_cumulative_and_ordered(self) -> None:
        registry = SuiteRegistry()
        registry.register(FakeSuite("z-smoke", Tier.T1))
        registry.register(FakeSuite("a-nightly", Tier.T2))
        registry.register(FakeSuite("m-release", Tier.T3))

        assert [s.name for s in registry.suites_for(Tier.T1)] == ["z-smoke"]
        assert [s.name for s in registry.suites_for(Tier.T2)] == ["a-nightly", "z-smoke"]
        assert len(registry.suites_for(Tier.T3)) == 3

    def test_default_registry_is_empty_at_m0(self) -> None:
        assert len(build_default_registry()) == 0


class TestRunner:
    def test_report_aggregates_outcomes(self) -> None:
        registry = SuiteRegistry()
        registry.register(FakeSuite("good", metrics={"score": 0.9}))
        registry.register(FakeSuite("bad", passed=False))

        report = run_tier(registry, Tier.T1)

        assert not report.passed
        by_name = {r.suite: r for r in report.results}
        assert by_name["good"].passed
        assert by_name["good"].metrics == {"score": 0.9}
        assert not by_name["bad"].passed
        assert by_name["bad"].failures == ["expected failure detail"]
        assert report.finished_at >= report.started_at

    def test_crashing_suite_is_contained(self) -> None:
        registry = SuiteRegistry()
        registry.register(FakeSuite("crashy", raises=True))
        registry.register(FakeSuite("healthy"))

        report = run_tier(registry, Tier.T1)

        by_name = {r.suite: r for r in report.results}
        assert not by_name["crashy"].passed
        assert by_name["crashy"].failures == ["suite raised RuntimeError"]
        assert by_name["healthy"].passed  # the crash did not abort the run

    def test_empty_registry_yields_passing_report(self) -> None:
        assert run_tier(SuiteRegistry(), Tier.T1).passed
