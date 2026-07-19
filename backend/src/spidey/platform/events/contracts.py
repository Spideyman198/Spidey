"""Domain-event contracts — the single source of truth (docs/08 §2).

An :class:`EventEnvelope` carries correlation + tracing metadata and a typed,
versioned ``payload``. Payloads are Pydantic models tagged with a stable
``event_type`` and ``schema_version``; evolution is additive (a breaking change
is a new type, never a mutated one), so a persisted event always re-validates.

Events are *facts published after the fact* — never commands. Nothing in a
payload instructs a consumer to act (ADR-0011); consumers observe and project.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field
from ulid import ULID


def new_event_id() -> str:
    """A ULID: lexicographically sortable by creation time, globally unique.

    Used as both the ordering key and the idempotency key for at-least-once
    delivery — consumers dedupe on it (docs/08 §4)."""
    return str(ULID())


class EventPayload(BaseModel):
    """Base for every event payload. Subclasses set ``event_type`` (stable, dotted,
    ``<context>.<fact>``) and ``schema_version`` (bumped on additive change)."""

    model_config = ConfigDict(frozen=True)

    event_type: ClassVar[str]
    schema_version: ClassVar[int] = 1


# ── llm context ───────────────────────────────────────────────────────────────
class LlmCallCompleted(EventPayload):
    event_type: ClassVar[str] = "llm.call_completed"

    provider: str
    model: str
    role: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    cost_usd: float
    # Reference into ``llm_interactions`` for full (redacted) request/response.
    interaction_id: uuid.UUID | None = None
    cached: bool = False


# ── tool plane ────────────────────────────────────────────────────────────────
class ToolInvocationStarted(EventPayload):
    event_type: ClassVar[str] = "tools.invocation_started"

    tool: str
    side_effect: str  # read | write | destructive
    trust_tier: str  # trusted | verified | untrusted


class ToolInvocationCompleted(EventPayload):
    event_type: ClassVar[str] = "tools.invocation_completed"

    tool: str
    side_effect: str
    outcome: str  # ok | error | unavailable | denied
    latency_ms: int


# ── chat/run lifecycle (minimal in M6; the agent runtime extends it in M7) ─────
class MessageReceived(EventPayload):
    event_type: ClassVar[str] = "chat.message_received"

    role: str  # user | assistant | system
    content_preview: str


class RunCompleted(EventPayload):
    event_type: ClassVar[str] = "chat.run_completed"

    outcome: str  # completed | failed
    reason: str | None = None


# ── agents runtime (M7) ────────────────────────────────────────────────────────
class RunStarted(EventPayload):
    event_type: ClassVar[str] = "agents.run_started"

    goal: str


class RunStatusChanged(EventPayload):
    event_type: ClassVar[str] = "agents.run_status_changed"

    status: str
    reason: str | None = None


class PlanCreated(EventPayload):
    event_type: ClassVar[str] = "agents.plan_created"

    version: int
    step_count: int


class ApprovalRequested(EventPayload):
    event_type: ClassVar[str] = "agents.approval_requested"

    approval_id: uuid.UUID
    tool: str
    side_effect: str


class ApprovalResolved(EventPayload):
    event_type: ClassVar[str] = "agents.approval_resolved"

    approval_id: uuid.UUID
    approved: bool


# ── coder / reviewer / git workflow (M8) ──────────────────────────────────────
class CodeGenerated(EventPayload):
    event_type: ClassVar[str] = "agents.code_generated"

    step_index: int
    files: list[str]  # workspace-relative paths the step edited


class ReviewCompleted(EventPayload):
    event_type: ClassVar[str] = "agents.review_completed"

    step_index: int
    iteration: int  # 1-based review round within the step
    verdict: str  # approved | changes_requested


class RunStepCommitted(EventPayload):
    event_type: ClassVar[str] = "agents.step_committed"

    step_index: int
    commit_sha: str
    branch: str


class CommitBlocked(EventPayload):
    event_type: ClassVar[str] = "agents.commit_blocked"

    step_index: int
    reason: str  # safe description — never carries the detected value


# ── execution / sandbox (M9) ──────────────────────────────────────────────────
class CommandExecuted(EventPayload):
    event_type: ClassVar[str] = "execution.command_executed"

    argv0: str  # only the executable name — never the full argv (may hold data)
    admitted: bool
    exit_code: int | None = None
    timed_out: bool = False
    network: str = "none"


class TestsCompleted(EventPayload):
    __test__ = False  # not a pytest test class despite the ``Test`` prefix

    event_type: ClassVar[str] = "execution.tests_completed"

    framework: str
    passed: bool
    passed_count: int | None = None
    failed_count: int | None = None


# ── debugger / documenter / PR delivery (M10) ─────────────────────────────────
class FixGenerated(EventPayload):
    event_type: ClassVar[str] = "agents.fix_generated"

    attempt: int  # 1-based debug attempt within the run
    files: list[str]  # workspace-relative paths the fix proposes to edit


class DocsGenerated(EventPayload):
    event_type: ClassVar[str] = "agents.docs_generated"

    summary_chars: int  # size only — the content lives in the run report


class PullRequestOpened(EventPayload):
    event_type: ClassVar[str] = "agents.pull_request_opened"

    number: int
    url: str
    branch: str


class RunReported(EventPayload):
    event_type: ClassVar[str] = "agents.run_reported"

    outcome: str  # completed | needs_human | failed
    steps: int
    tests_passed: bool | None = None
    pull_request_url: str | None = None


# Registry: event_type → payload model, for re-validation on read (replay/SSE).
EVENT_TYPES: dict[str, type[EventPayload]] = {
    payload.event_type: payload
    for payload in (
        LlmCallCompleted,
        ToolInvocationStarted,
        ToolInvocationCompleted,
        MessageReceived,
        RunCompleted,
        RunStarted,
        RunStatusChanged,
        PlanCreated,
        ApprovalRequested,
        ApprovalResolved,
        CodeGenerated,
        ReviewCompleted,
        RunStepCommitted,
        CommitBlocked,
        CommandExecuted,
        TestsCompleted,
        FixGenerated,
        DocsGenerated,
        PullRequestOpened,
        RunReported,
    )
}


class EventEnvelope(BaseModel):
    """A domain event as it is stored, streamed, and replayed."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=new_event_id)
    event_type: str
    schema_version: int
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    # Correlation — any may be None for a platform-level event.
    run_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    actor: str | None = None
    # OTel linkage: every event joins a trace (docs/08 §2).
    trace_id: str | None = None
    span_id: str | None = None
    payload: dict[str, Any]

    @classmethod
    def of(
        cls,
        payload: EventPayload,
        *,
        run_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        workspace_id: uuid.UUID | None = None,
        actor: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> EventEnvelope:
        """Build an envelope from a typed payload, deriving type + version."""
        return cls(
            event_type=payload.event_type,
            schema_version=payload.schema_version,
            run_id=run_id,
            session_id=session_id,
            workspace_id=workspace_id,
            actor=actor,
            trace_id=trace_id,
            span_id=span_id,
            payload=payload.model_dump(mode="json"),
        )

    def validated_payload(self) -> EventPayload:
        """Re-parse the payload against its registered model (raises if unknown)."""
        model = EVENT_TYPES.get(self.event_type)
        if model is None:
            msg = f"unknown event_type {self.event_type!r}"
            raise ValueError(msg)
        return model.model_validate(self.payload)
