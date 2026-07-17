"""LangGraph run state (ADR-0002).

Kept JSON-serializable primitives so the checkpointer can persist it and a run
can resume across an API restart. The graph owns control flow; this is the data
that flows between nodes.
"""

from __future__ import annotations

from typing import TypedDict


class RunState(TypedDict):
    run_id: str
    owner_id: str
    workspace_id: str | None
    goal: str
    # Plan steps as serialized dicts ({index, title, detail, status}).
    plan: list[dict[str, object]]
    step_index: int
    # Human-readable notes accumulated per step (for the transcript / finalize).
    transcript: list[str]
    status: str
    # ── coder/reviewer workflow (M8) ─────────────────────────────────────────
    # Write-tool calls awaiting human approval ({approval_id, tool, arguments}).
    proposals: list[dict[str, object]]
    # Workspace-relative paths edited during the current step.
    applied: list[str]
    # Reviewer feedback carried into the coder's retry ("" when none).
    critique: str
    # 0-based count of completed review rounds within the current step.
    review_round: int
    # Run-branch git anchors ("" / None when the run has no workspace).
    branch: str
    base_commit: str | None


def initial_state(*, run_id: str, owner_id: str, workspace_id: str | None, goal: str) -> RunState:
    """A fresh run state — every key present so the graph can start cleanly."""
    return RunState(
        run_id=run_id,
        owner_id=owner_id,
        workspace_id=workspace_id,
        goal=goal,
        plan=[],
        step_index=0,
        transcript=[],
        status="pending",
        proposals=[],
        applied=[],
        critique="",
        review_round=0,
        branch="",
        base_commit=None,
    )
