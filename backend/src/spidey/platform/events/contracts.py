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


# Registry: event_type → payload model, for re-validation on read (replay/SSE).
EVENT_TYPES: dict[str, type[EventPayload]] = {
    payload.event_type: payload
    for payload in (
        LlmCallCompleted,
        ToolInvocationStarted,
        ToolInvocationCompleted,
        MessageReceived,
        RunCompleted,
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
