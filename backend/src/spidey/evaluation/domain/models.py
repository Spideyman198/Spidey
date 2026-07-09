"""Evaluation domain model.

Contracts:
- Tiers are cumulative: running T2 executes every suite tagged T1 or T2, so a
  nightly run can never silently skip what a PR run enforces (docs/10 §4).
- A suite reports a :class:`SuiteOutcome`; the runner owns timing and error
  containment and produces the immutable :class:`SuiteResult` record.
- Metrics are plain ``name -> float`` so baselines, reports, and dashboards
  need no per-suite schema knowledge.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class Tier(StrEnum):
    T1 = "t1"  # PR smoke: deterministic, LLM-free, free of charge
    T2 = "t2"  # nightly: live model, budgeted
    T3 = "t3"  # release: everything, approved budget

    @property
    def rank(self) -> int:
        return {"t1": 1, "t2": 2, "t3": 3}[self.value]

    def includes(self, other: Tier) -> bool:
        """A run at this tier executes suites tagged at ``other``."""
        return other.rank <= self.rank


class SuiteOutcome(BaseModel):
    """What a suite reports about its own run."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    metrics: dict[str, float] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)


@runtime_checkable
class EvalSuite(Protocol):
    """Contract for a benchmark suite.

    Implementations must be deterministic at T1 (no network, no live models)
    and must raise rather than fabricate results — the runner records an
    exception as a failed suite with the exception class name.
    """

    @property
    def name(self) -> str: ...

    @property
    def tier(self) -> Tier: ...

    def run(self) -> SuiteOutcome: ...


class SuiteResult(BaseModel):
    """Immutable record of one suite execution, produced by the runner."""

    model_config = ConfigDict(frozen=True)

    suite: str
    tier: Tier
    passed: bool
    metrics: dict[str, float] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)
    duration_seconds: float


class EvalReport(BaseModel):
    """Full result of a tier run; serialized as-is into evaluation/reports/."""

    model_config = ConfigDict(frozen=True)

    tier: Tier
    started_at: datetime
    finished_at: datetime
    results: list[SuiteResult] = Field(default_factory=list[SuiteResult])

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def suite_names(self) -> list[str]:
        return [result.suite for result in self.results]


class BaselineViolation(BaseModel):
    """A metric that fell below its blessed minimum."""

    model_config = ConfigDict(frozen=True)

    suite: str
    metric: str
    minimum: float
    actual: float

    def describe(self) -> str:
        return f"{self.suite}.{self.metric}: {self.actual} < blessed minimum {self.minimum}"
