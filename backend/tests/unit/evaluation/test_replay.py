"""Golden-replay eval mechanics: timeline diff + suite pass/fail (LLM-free)."""

from __future__ import annotations

from spidey.evaluation.application import AgentReplayEvalSuite
from spidey.evaluation.domain import ReplayCase, ReplayTimeline, Tier, diff_timeline

_TIMELINE = ReplayTimeline(
    status="completed",
    plan=["a", "b"],
    transcript=["[a] did a", "[b] did b"],
    events=["agents.plan_created", "chat.run_completed"],
)


def _case() -> ReplayCase:
    return ReplayCase(
        name="c", goal="g", planner_lines=["a", "b"], expected=_TIMELINE
    )


def test_diff_timeline_identical_is_empty() -> None:
    assert diff_timeline(_TIMELINE, _TIMELINE) == []


def test_diff_timeline_reports_each_divergent_field() -> None:
    other = _TIMELINE.model_copy(update={"status": "failed", "plan": ["a"]})
    diffs = diff_timeline(_TIMELINE, other)
    assert len(diffs) == 2
    assert any("status" in d for d in diffs)
    assert any("plan" in d for d in diffs)


def test_suite_passes_when_replay_is_deterministic_and_matches_golden() -> None:
    suite = AgentReplayEvalSuite(cases=[_case()], replay=lambda _case: _TIMELINE)
    outcome = suite.run()
    assert outcome.passed
    assert outcome.metrics == {"determinism_rate": 1.0, "golden_match_rate": 1.0}


def test_suite_fails_on_nondeterministic_replay() -> None:
    calls = {"n": 0}

    def flaky(_case: ReplayCase) -> ReplayTimeline:
        calls["n"] += 1
        status = "completed" if calls["n"] % 2 == 1 else "failed"
        return _TIMELINE.model_copy(update={"status": status})

    suite = AgentReplayEvalSuite(cases=[_case()], replay=flaky)
    outcome = suite.run()
    assert not outcome.passed
    assert outcome.metrics["determinism_rate"] == 0.0


def test_suite_fails_when_replay_diverges_from_golden() -> None:
    drifted = _TIMELINE.model_copy(update={"transcript": ["[a] different"]})
    suite = AgentReplayEvalSuite(cases=[_case()], replay=lambda _case: drifted)
    outcome = suite.run()
    assert not outcome.passed
    assert outcome.metrics["golden_match_rate"] == 0.0


def test_empty_suite_passes() -> None:
    suite = AgentReplayEvalSuite(cases=[], replay=lambda _case: _TIMELINE)
    outcome = suite.run()
    assert outcome.passed
    assert suite.tier is Tier.T1
