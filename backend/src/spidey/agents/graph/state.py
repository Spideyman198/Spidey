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
    )
