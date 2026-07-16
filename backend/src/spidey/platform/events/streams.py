"""Redis Streams transport for the event plane (ADR-0006, docs/08 §4).

Two readerships over the same relayed events:
- **SSE** reads a per-run stream (``run:{id}:events``) from a client cursor, so a
  refreshing browser or a restarted API resumes without loss.
- **Consumer groups** (persister, audit, metrics) read the firehose
  (``events:all``) with at-least-once delivery and per-consumer acks.

Streams are capped (``MAXLEN ~``) and the durable record lives in Postgres, so
Redis is a fast relay, never the system of record.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from redis.exceptions import ResponseError

if TYPE_CHECKING:
    from redis.asyncio import Redis

_DATA_FIELD = "data"
_DEFAULT_MAXLEN = 10_000


class StreamBus:
    """Thin, typed wrapper over the Redis Streams commands the event plane uses."""

    def __init__(self, redis: Redis, *, maxlen: int = _DEFAULT_MAXLEN) -> None:
        self._redis = redis
        self._maxlen = maxlen

    async def publish(self, stream_key: str, data: str) -> str:
        """Append one event (JSON ``data``) to a stream; returns its stream id."""
        return await self._redis.xadd(
            stream_key, {_DATA_FIELD: data}, maxlen=self._maxlen, approximate=True
        )

    async def read(
        self, stream_key: str, *, last_id: str, block_ms: int, count: int
    ) -> list[tuple[str, str]]:
        """One blocking read of new messages after ``last_id`` (SSE loop step)."""
        result = await self._redis.xread({stream_key: last_id}, count=count, block=block_ms)
        if not result:
            return []
        _stream, messages = result[0]
        return [(message_id, fields[_DATA_FIELD]) for message_id, fields in messages]

    async def ensure_group(self, stream_key: str, group: str) -> None:
        """Create a consumer group at the stream tail; idempotent."""
        try:
            await self._redis.xgroup_create(stream_key, group, id="0", mkstream=True)
        except ResponseError as exc:
            # BUSYGROUP = the group already exists; anything else is a real error.
            if "BUSYGROUP" not in str(exc):
                raise

    async def read_group(
        self, stream_key: str, *, group: str, consumer: str, count: int, block_ms: int
    ) -> list[tuple[str, str]]:
        """Read undelivered messages for a consumer group (at-least-once)."""
        result = await self._redis.xreadgroup(
            group, consumer, {stream_key: ">"}, count=count, block=block_ms
        )
        if not result:
            return []
        _stream, messages = result[0]
        return [(mid, fields[_DATA_FIELD]) for mid, fields in messages if fields]

    async def ack(self, stream_key: str, *, group: str, message_id: str) -> None:
        await self._redis.xack(stream_key, group, message_id)
