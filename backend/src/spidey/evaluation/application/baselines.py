"""Blessed-baseline loading and regression checking.

Baseline files live in ``evaluation/baselines/<suite>.json`` as
``{"<metric>": {"min": <float>}}`` and change only via reviewed re-bless
commits (docs/10 §4). A baseline for a suite that did not run at this tier is
ignored — lower tiers must not fail on higher-tier expectations.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from spidey.evaluation.domain import BaselineViolation
from spidey.platform.errors import ValidationFailedError

if TYPE_CHECKING:
    from pathlib import Path

    from spidey.evaluation.domain import EvalReport


class MetricBaseline(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min: float


def load_baselines(directory: Path) -> dict[str, dict[str, MetricBaseline]]:
    """Load all ``<suite>.json`` baseline files; a missing directory is empty."""
    if not directory.is_dir():
        return {}
    baselines: dict[str, dict[str, MetricBaseline]] = {}
    for file in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
            baselines[file.stem] = {
                metric: MetricBaseline.model_validate(spec) for metric, spec in raw.items()
            }
        except (json.JSONDecodeError, ValueError) as exc:
            msg = f"baseline file {file.name} is malformed: {type(exc).__name__}"
            raise ValidationFailedError(msg, file=str(file)) from exc
    return baselines


def check_baselines(
    report: EvalReport,
    baselines: dict[str, dict[str, MetricBaseline]],
) -> list[BaselineViolation]:
    """Compare a report against blessed minimums; empty list means green."""
    violations: list[BaselineViolation] = []
    results_by_suite = {result.suite: result for result in report.results}

    for suite_name, metric_baselines in baselines.items():
        result = results_by_suite.get(suite_name)
        if result is None:
            continue  # suite not part of this tier's run
        for metric, baseline in metric_baselines.items():
            actual = result.metrics.get(metric)
            if actual is None:
                violations.append(
                    BaselineViolation(
                        suite=suite_name, metric=metric, minimum=baseline.min, actual=float("nan")
                    )
                )
            elif actual < baseline.min:
                violations.append(
                    BaselineViolation(
                        suite=suite_name, metric=metric, minimum=baseline.min, actual=actual
                    )
                )
    return violations
