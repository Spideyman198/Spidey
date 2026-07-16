"""Agent golden-replay suite (T1): proves runs are reproducible (docs/10 §4).

The suite is transport-agnostic: it drives a plain ``replay(case) -> timeline``
callable, so the same suite grades an in-memory graph replay (the unit/integration
harness) or any future recorded-run reconstruction. For every case it (1) replays
twice and requires the two timelines to be identical — catching hidden
non-determinism — and (2) requires the replay to match the golden timeline
checked into the dataset. Being LLM- and network-free, it runs on every PR (T1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.evaluation.domain import SuiteOutcome, Tier, diff_timeline

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from spidey.evaluation.domain import ReplayCase, ReplayTimeline


class AgentReplayEvalSuite:
    """Grades run reproducibility over golden cases; satisfies ``EvalSuite``."""

    def __init__(
        self,
        *,
        cases: Sequence[ReplayCase],
        replay: Callable[[ReplayCase], ReplayTimeline],
        name: str = "agent_replay",
        tier: Tier = Tier.T1,
    ) -> None:
        self._cases = list(cases)
        self._replay = replay
        self._name = name
        self._tier = tier

    @property
    def name(self) -> str:
        return self._name

    @property
    def tier(self) -> Tier:
        return self._tier

    def run(self) -> SuiteOutcome:
        if not self._cases:
            return SuiteOutcome(passed=True, metrics={}, failures=[])

        deterministic = 0
        matched = 0
        failures: list[str] = []

        for case in self._cases:
            first = self._replay(case)
            second = self._replay(case)
            if first == second:
                deterministic += 1
            else:
                failures.extend(
                    f"{case.name}: non-deterministic replay: {d}"
                    for d in diff_timeline(first, second)
                )
            diffs = diff_timeline(case.expected, first)
            if not diffs:
                matched += 1
            else:
                failures.extend(f"{case.name}: {d}" for d in diffs)

        total = len(self._cases)
        metrics = {
            "determinism_rate": round(deterministic / total, 4),
            "golden_match_rate": round(matched / total, 4),
        }
        return SuiteOutcome(passed=not failures, metrics=metrics, failures=failures)
