"""Durable event reader — timeline reconstruction from ``run_events`` (docs/08 §5).

Reads the persisted spine for a run in occurrence order. The SSE endpoint uses
this to replay history before switching to the live Redis stream, so a client
that connects late still sees the whole run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from spidey.platform.events.contracts import EventEnvelope
from spidey.platform.events.orm import RunEventRecord

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


class RunEventReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def timeline(self, run_id: uuid.UUID, *, limit: int = 1000) -> list[EventEnvelope]:
        records = await self._session.scalars(
            select(RunEventRecord)
            .where(RunEventRecord.run_id == run_id)
            .order_by(RunEventRecord.occurred_at, RunEventRecord.event_id)
            .limit(limit)
        )
        return [self._to_envelope(r) for r in records]

    @staticmethod
    def _to_envelope(r: RunEventRecord) -> EventEnvelope:
        return EventEnvelope(
            event_id=r.event_id,
            event_type=r.event_type,
            schema_version=r.schema_version,
            occurred_at=r.occurred_at,
            run_id=r.run_id,
            session_id=r.session_id,
            workspace_id=r.workspace_id,
            actor=r.actor,
            trace_id=r.trace_id,
            span_id=r.span_id,
            payload=r.payload,
        )
