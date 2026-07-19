"""Run report — a structured summary of one run (M10).

Reconstructed from the durable event timeline plus the run record and plan, so
the report is a *projection* of what actually happened (commits, test verdict,
pull request, outcome), never a separately-maintained truth. Pure and
side-effect-free: the API assembles the inputs and this builds the report.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from spidey.agents.domain.runs import Plan, Run
    from spidey.platform.events import EventEnvelope


class ReportStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int
    title: str
    status: str


class RunReport(BaseModel):
    """The run's outcome at a glance — for the UI, a PR body, or an audit."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    goal: str
    status: str
    outcome: str  # completed | needs_human | failed | in_progress
    steps: list[ReportStep] = Field(default_factory=list[ReportStep])
    commits: list[str] = Field(default_factory=list[str])
    tests_passed: bool | None = None
    pull_request_url: str | None = None
    event_count: int = 0


def build_run_report(run: Run, plan: Plan | None, events: list[EventEnvelope]) -> RunReport:
    commits: list[str] = []
    tests_passed: bool | None = None
    pr_url: str | None = None
    outcome = "in_progress"

    for event in events:
        payload = event.payload
        if event.event_type == "agents.step_committed":
            sha = payload.get("commit_sha")
            if isinstance(sha, str):
                commits.append(sha)
        elif event.event_type == "execution.tests_completed":
            tests_passed = bool(payload.get("passed"))
        elif event.event_type == "agents.pull_request_opened":
            url = payload.get("url")
            pr_url = url if isinstance(url, str) else pr_url
        elif event.event_type == "agents.run_reported":
            outcome = str(payload.get("outcome", outcome))
            if payload.get("tests_passed") is not None:
                tests_passed = bool(payload["tests_passed"])
            reported_pr = payload.get("pull_request_url")
            pr_url = reported_pr if isinstance(reported_pr, str) else pr_url

    steps = (
        [ReportStep(index=s.index, title=s.title, status=s.status.value) for s in plan.steps]
        if plan is not None
        else []
    )
    return RunReport(
        run_id=str(run.id),
        goal=run.goal,
        status=run.status.value,
        outcome=outcome,
        steps=steps,
        commits=commits,
        tests_passed=tests_passed,
        pull_request_url=pr_url,
        event_count=len(events),
    )
