"""Outbox relay: drains committed outbox rows to Redis Streams (docs/08 §4).

Runs out-of-band from producers. Each event is fanned to the firehose
(``events:all``, for consumer groups) and, for a run event, to its per-run stream
(for SSE), then the row is marked relayed. Publishing is at-least-once — a crash
after publish but before the mark re-publishes, and every consumer dedupes on the
ULID ``event_id`` — so no event is ever lost.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from spidey.platform.events.orm import OutboxRecord
from spidey.platform.events.outbox import stream_key_for
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from spidey.platform.events.streams import StreamBus

_FIREHOSE = stream_key_for(None)
_logger = get_logger("spidey.events.relay")


class OutboxRelay:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], bus: StreamBus) -> None:
        self._session_factory = session_factory
        self._bus = bus

    async def drain(self, *, batch: int = 128) -> int:
        """Relay up to ``batch`` pending events; returns how many were relayed."""
        async with self._session_factory() as session:
            rows = await self._claim(session, batch)
            for row in rows:
                data = _json(row.envelope)
                # Firehose for consumer groups; per-run stream for SSE (if distinct).
                await self._bus.publish(_FIREHOSE, data)
                if row.stream_key != _FIREHOSE:
                    await self._bus.publish(row.stream_key, data)
                await self._mark_relayed(session, row)
            await session.commit()
        if rows:
            _logger.info("outbox_relayed", count=len(rows))
        return len(rows)

    @staticmethod
    async def _claim(session: AsyncSession, batch: int) -> list[OutboxRecord]:
        result = await session.scalars(
            select(OutboxRecord)
            .where(OutboxRecord.relayed_at.is_(None))
            .order_by(OutboxRecord.created_at)
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
        return list(result)

    @staticmethod
    async def _mark_relayed(session: AsyncSession, row: OutboxRecord) -> None:
        row.relayed_at = datetime.now(tz=UTC)
        await session.flush()


def _json(envelope: dict[str, object]) -> str:
    return json.dumps(envelope, separators=(",", ":"))
