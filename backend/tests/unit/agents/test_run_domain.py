"""Run lifecycle state machine and budget exhaustion (M7 domain)."""

from __future__ import annotations

from spidey.agents.domain import RunBudget, RunStatus, can_transition, is_terminal


class TestTransitions:
    def test_valid_forward_flow(self) -> None:
        assert can_transition(RunStatus.PENDING, RunStatus.PLANNING)
        assert can_transition(RunStatus.PLANNING, RunStatus.AWAITING_APPROVAL)
        assert can_transition(RunStatus.AWAITING_APPROVAL, RunStatus.RUNNING)
        assert can_transition(RunStatus.RUNNING, RunStatus.COMPLETED)

    def test_invalid_transitions_rejected(self) -> None:
        assert not can_transition(RunStatus.PENDING, RunStatus.COMPLETED)
        assert not can_transition(RunStatus.COMPLETED, RunStatus.RUNNING)  # terminal
        assert not can_transition(RunStatus.RUNNING, RunStatus.PENDING)

    def test_budget_halts_into_needs_human(self) -> None:
        assert can_transition(RunStatus.RUNNING, RunStatus.NEEDS_HUMAN)
        assert can_transition(RunStatus.NEEDS_HUMAN, RunStatus.RUNNING)  # resumable

    def test_terminal_states(self) -> None:
        assert is_terminal(RunStatus.COMPLETED)
        assert is_terminal(RunStatus.FAILED)
        assert is_terminal(RunStatus.CANCELLED)
        assert not is_terminal(RunStatus.RUNNING)


class TestBudget:
    def test_exhausted_on_any_dimension(self) -> None:
        assert not RunBudget(max_steps=10, steps_used=3).exhausted()
        assert RunBudget(max_steps=10, steps_used=10).exhausted()
        assert RunBudget(max_tokens=100, tokens_used=100).exhausted()
        assert RunBudget(max_cost_usd=1.0, cost_used=1.5).exhausted()
