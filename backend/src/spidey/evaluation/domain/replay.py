"""Agent golden-replay model (M7 exit criterion, docs/10).

A run's *timeline* — the ordered plan, per-step notes, terminal status, and the
event sequence — is the deterministic artifact of an agent run. Replaying the
same recorded model/tool responses must reproduce that timeline byte-for-byte;
if it does not, the run is not reproducible and a regression is invisible.

These types are pure and JSON-serializable so a golden timeline lives in the
repo (``evaluation/datasets/agent_replay/``) and the diff is unit-testable with
no model, graph, or database.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReplayTimeline(BaseModel):
    """The reproducible outcome of one run replay."""

    model_config = ConfigDict(frozen=True)

    status: str
    plan: list[str] = Field(default_factory=list[str])
    transcript: list[str] = Field(default_factory=list[str])
    events: list[str] = Field(default_factory=list[str])


class ReplayCase(BaseModel):
    """A recorded run: the scripted model responses plus the golden timeline the
    replay must reproduce. ``planner_lines`` are the plan the planner emits (one
    step per line); ``coder_notes`` are the coder's reply for each executed step."""

    model_config = ConfigDict(frozen=True)

    name: str
    goal: str
    planner_lines: list[str] = Field(default_factory=list[str])
    coder_notes: list[str] = Field(default_factory=list[str])
    expected: ReplayTimeline


def diff_timeline(expected: ReplayTimeline, actual: ReplayTimeline) -> list[str]:
    """Field-by-field differences between two timelines; empty ⇒ exact match."""
    diffs: list[str] = []
    if expected.status != actual.status:
        diffs.append(f"status: expected {expected.status!r}, got {actual.status!r}")
    if expected.plan != actual.plan:
        diffs.append(f"plan: expected {expected.plan}, got {actual.plan}")
    if expected.transcript != actual.transcript:
        diffs.append(
            f"transcript: expected {expected.transcript}, got {actual.transcript}"
        )
    if expected.events != actual.events:
        diffs.append(f"events: expected {expected.events}, got {actual.events}")
    return diffs
