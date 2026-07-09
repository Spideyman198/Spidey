"""Evaluation CLI: ``python -m spidey.evaluation run --tier t1 --check-baselines``.

Exit codes: 0 = all suites passed and baselines hold; 1 = a suite failed or a
baseline was violated; 2 = usage error. CI treats non-zero as a failed gate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from spidey.evaluation.application import (
    build_default_registry,
    check_baselines,
    load_baselines,
    run_tier,
)
from spidey.evaluation.domain import Tier
from spidey.evaluation.infrastructure import write_report

_DEFAULT_BASELINES = Path("../evaluation/baselines")
_DEFAULT_REPORTS = Path("../evaluation/reports")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spidey.evaluation")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="run the suites for a tier")
    run.add_argument("--tier", type=Tier, choices=list(Tier), default=Tier.T1)
    run.add_argument("--check-baselines", action="store_true")
    run.add_argument("--baselines-dir", type=Path, default=_DEFAULT_BASELINES)
    run.add_argument("--reports-dir", type=Path, default=_DEFAULT_REPORTS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    registry = build_default_registry()
    report = run_tier(registry, args.tier)
    report_path = write_report(report, args.reports_dir)

    if not report.results:
        print(
            f"[{args.tier.value}] no suites registered for this tier — pass (report: {report_path})"
        )
        return 0

    for result in report.results:
        marker = "PASS" if result.passed else "FAIL"
        line = f"[{args.tier.value}] {marker} {result.suite} ({result.duration_seconds}s)"
        print(f"{line} {result.metrics}")
        for failure in result.failures:
            print(f"         - {failure}")

    exit_code = 0 if report.passed else 1

    if args.check_baselines:
        violations = check_baselines(report, load_baselines(args.baselines_dir))
        for violation in violations:
            print(f"[{args.tier.value}] BASELINE VIOLATION {violation.describe()}")
        if violations:
            exit_code = 1

    print(f"[{args.tier.value}] report written to {report_path}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
