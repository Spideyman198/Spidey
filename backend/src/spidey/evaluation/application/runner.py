"""Tier runner: executes suites with timing and error containment."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spidey.evaluation.domain import EvalReport, SuiteResult
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from spidey.evaluation.application.registry import SuiteRegistry
    from spidey.evaluation.domain import Tier

_logger = get_logger("spidey.evaluation.runner")


def run_tier(registry: SuiteRegistry, tier: Tier) -> EvalReport:
    """Run every suite selected for ``tier``.

    A raising suite becomes a failed :class:`SuiteResult` carrying the
    exception class name — one broken suite never aborts the report the other
    suites earned.
    """
    started_at = datetime.now(tz=UTC)
    results: list[SuiteResult] = []

    for suite in registry.suites_for(tier):
        t0 = time.perf_counter()
        try:
            outcome = suite.run()
            result = SuiteResult(
                suite=suite.name,
                tier=suite.tier,
                passed=outcome.passed,
                metrics=outcome.metrics,
                failures=outcome.failures,
                duration_seconds=round(time.perf_counter() - t0, 3),
            )
        except Exception as exc:
            result = SuiteResult(
                suite=suite.name,
                tier=suite.tier,
                passed=False,
                failures=[f"suite raised {type(exc).__name__}"],
                duration_seconds=round(time.perf_counter() - t0, 3),
            )
            _logger.exception("suite_crashed", suite=suite.name)
        _logger.info(
            "suite_finished",
            suite=result.suite,
            passed=result.passed,
            duration_seconds=result.duration_seconds,
        )
        results.append(result)

    return EvalReport(
        tier=tier,
        started_at=started_at,
        finished_at=datetime.now(tz=UTC),
        results=results,
    )
