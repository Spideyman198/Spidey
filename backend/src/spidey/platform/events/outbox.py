"""Transactional-outbox writer (the producer side of the event plane).

Adds the event as an :class:`OutboxRecord` to the caller's session, so it is
committed in the same transaction as the state change it describes. A separate
relay drains committed rows to Redis Streams — the write path never blocks on
Redis, and a crash between commit and relay just leaves the row to be picked up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.platform.events.orm import OutboxRecord

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from spidey.platform.events.contracts import EventEnvelope

_FIREHOSE = "events:all"


def stream_key_for(run_id: uuid.UUID | None) -> str:
    """Per-run stream for SSE, or the firehose for run-less platform events."""
    return f"run:{run_id}:events" if run_id is not None else _FIREHOSE


class OutboxWriter:
    """Session-scoped :class:`EventPublisher`. One per unit of work."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, envelope: EventEnvelope) -> None:
        self._session.add(
            OutboxRecord(
                event_id=envelope.event_id,
                stream_key=stream_key_for(envelope.run_id),
                envelope=envelope.model_dump(mode="json"),
            )
        )
