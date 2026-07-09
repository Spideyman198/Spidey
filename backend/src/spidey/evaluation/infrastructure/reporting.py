"""Report persistence: one JSON file per run under evaluation/reports/."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from spidey.evaluation.domain import EvalReport


def write_report(report: EvalReport, directory: Path) -> Path:
    """Serialize the report; the filename is sortable and collision-free."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report.started_at.strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"eval-{report.tier.value}-{stamp}.json"
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path
