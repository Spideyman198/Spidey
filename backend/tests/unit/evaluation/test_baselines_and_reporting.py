"""Baseline gating and report persistence."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from spidey.evaluation.application import check_baselines, load_baselines
from spidey.evaluation.domain import EvalReport, SuiteResult, Tier
from spidey.evaluation.infrastructure import write_report
from spidey.platform.errors import ValidationFailedError

if TYPE_CHECKING:
    from pathlib import Path


def _report(metrics: dict[str, float], suite: str = "retrieval") -> EvalReport:
    now = datetime.now(tz=UTC)
    return EvalReport(
        tier=Tier.T1,
        started_at=now,
        finished_at=now,
        results=[
            SuiteResult(
                suite=suite, tier=Tier.T1, passed=True, metrics=metrics, duration_seconds=1.0
            )
        ],
    )


class TestBaselines:
    def test_missing_directory_is_empty(self, tmp_path: Path) -> None:
        assert load_baselines(tmp_path / "nope") == {}

    def test_violation_below_minimum(self, tmp_path: Path) -> None:
        (tmp_path / "retrieval.json").write_text(json.dumps({"precision_at_10": {"min": 0.8}}))
        violations = check_baselines(_report({"precision_at_10": 0.7}), load_baselines(tmp_path))
        assert len(violations) == 1
        assert violations[0].describe() == "retrieval.precision_at_10: 0.7 < blessed minimum 0.8"

    def test_meeting_minimum_is_green(self, tmp_path: Path) -> None:
        (tmp_path / "retrieval.json").write_text(json.dumps({"precision_at_10": {"min": 0.8}}))
        assert check_baselines(_report({"precision_at_10": 0.8}), load_baselines(tmp_path)) == []

    def test_missing_metric_is_a_violation(self, tmp_path: Path) -> None:
        (tmp_path / "retrieval.json").write_text(json.dumps({"recall_at_10": {"min": 0.5}}))
        violations = check_baselines(_report({"other": 1.0}), load_baselines(tmp_path))
        assert len(violations) == 1
        assert math.isnan(violations[0].actual)

    def test_baseline_for_suite_not_run_is_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "agent-tasks.json").write_text(json.dumps({"success_rate": {"min": 0.5}}))
        assert check_baselines(_report({}, suite="retrieval"), load_baselines(tmp_path)) == []

    def test_malformed_baseline_fails_loudly(self, tmp_path: Path) -> None:
        (tmp_path / "retrieval.json").write_text("{not json")
        with pytest.raises(ValidationFailedError):
            load_baselines(tmp_path)

    def test_unknown_baseline_keys_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "retrieval.json").write_text(json.dumps({"m": {"min": 0.1, "max": 0.9}}))
        with pytest.raises(ValidationFailedError):
            load_baselines(tmp_path)


class TestReporting:
    def test_report_round_trips(self, tmp_path: Path) -> None:
        report = _report({"score": 0.5})
        path = write_report(report, tmp_path / "reports")

        assert path.name.startswith("eval-t1-")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["tier"] == "t1"
        assert loaded["results"][0]["suite"] == "retrieval"
        assert loaded["results"][0]["metrics"] == {"score": 0.5}
