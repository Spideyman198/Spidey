"""Event persistence: the transactional outbox and the durable event log.

``OutboxRecord`` is written in the *same* transaction as the state change it
describes; the relay drains committed rows to Redis Streams and marks them
relayed — so a crash never loses or invents an event (docs/08 §4).
``RunEventRecord`` is the durable spine the persister consumer projects the
stream into, and the source for timeline reconstruction and replay.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from spidey.platform.db import Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class OutboxRecord(Base):
    """One pending (or relayed) event. Insert-only; the relay flips ``relayed_at``."""

    __tablename__ = "event_outbox"
    __table_args__ = (
        # The relay polls unrelayed rows oldest-first; a partial index keeps that
        # scan cheap as the table grows and rows are drained.
        Index(
            "ix_event_outbox_unrelayed",
            "created_at",
            postgresql_where="relayed_at IS NULL",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # ULID from the envelope — the idempotency key consumers dedupe on.
    event_id: Mapped[str] = mapped_column(String(26), unique=True)
    # Target Redis stream (per-run stream or the firehose).
    stream_key: Mapped[str] = mapped_column(String(256))
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    relayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEventRecord(Base):
    """The durable, ordered event log — projected from the stream by the persister.

    Insert-only (append-only audit spine); ``event_id`` is the ULID primary key,
    so a duplicated delivery is an idempotent upsert-noop."""

    __tablename__ = "run_events"
    __table_args__ = (Index("ix_run_events_run_occurred", "run_id", "occurred_at"),)

    event_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128))
    schema_version: Mapped[int] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column()
    actor: Mapped[str | None] = mapped_column(String(256))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    span_id: Mapped[str | None] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    persisted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
