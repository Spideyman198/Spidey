"""Suite fakes shared by evaluation tests."""

from __future__ import annotations

from spidey.evaluation.domain import SuiteOutcome, Tier


class FakeSuite:
    def __init__(
        self,
        name: str,
        tier: Tier = Tier.T1,
        *,
        passed: bool = True,
        metrics: dict[str, float] | None = None,
        raises: bool = False,
    ) -> None:
        self._name = name
        self._tier = tier
        self._passed = passed
        self._metrics = metrics or {}
        self._raises = raises

    @property
    def name(self) -> str:
        return self._name

    @property
    def tier(self) -> Tier:
        return self._tier

    def run(self) -> SuiteOutcome:
        if self._raises:
            msg = "synthetic suite crash"
            raise RuntimeError(msg)
        failures = [] if self._passed else ["expected failure detail"]
        return SuiteOutcome(passed=self._passed, metrics=self._metrics, failures=failures)
