"""build_run_report projects the event timeline into a run summary (pure)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from spidey.agents.application import build_run_report
from spidey.agents.domain.runs import Plan, PlanStep, Run, RunStatus, StepStatus
from spidey.platform.events import (
    EventEnvelope,
    PullRequestOpened,
    RunReported,
    RunStepCommitted,
    TestsCompleted,
)


def _run() -> Run:
    now = datetime.now(tz=UTC)
    return Run(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        session_id=None,
        goal="fix the bug",
        status=RunStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )


def _plan() -> Plan:
    return Plan(
        version=1,
        steps=[PlanStep(index=0, title="patch it", status=StepStatus.DONE)],
    )


def _events(run_id: uuid.UUID) -> list[EventEnvelope]:
    return [
        EventEnvelope.of(
            RunStepCommitted(step_index=0, commit_sha="abc123", branch="spidey/run-x"),
            run_id=run_id,
        ),
        EventEnvelope.of(
            TestsCompleted(framework="pytest", passed=True, passed_count=3), run_id=run_id
        ),
        EventEnvelope.of(
            PullRequestOpened(number=7, url="https://github.com/o/r/pull/7", branch="spidey/run-x"),
            run_id=run_id,
        ),
        EventEnvelope.of(
            RunReported(
                outcome="completed",
                steps=1,
                tests_passed=True,
                pull_request_url="https://github.com/o/r/pull/7",
            ),
            run_id=run_id,
        ),
    ]


def test_report_projects_commits_tests_and_pr() -> None:
    run = _run()
    report = build_run_report(run, _plan(), _events(run.id))
    assert report.goal == "fix the bug"
    assert report.outcome == "completed"
    assert report.commits == ["abc123"]
    assert report.tests_passed is True
    assert report.pull_request_url == "https://github.com/o/r/pull/7"
    assert [s.title for s in report.steps] == ["patch it"]
    assert report.event_count == 4


def test_report_without_plan_or_events_is_in_progress() -> None:
    run = _run()
    report = build_run_report(run, None, [])
    assert report.outcome == "in_progress"
    assert report.steps == []
    assert report.tests_passed is None
    assert report.pull_request_url is None
