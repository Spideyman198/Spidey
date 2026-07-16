"""Redis response cache (ResponseCache adapter).

Exact-match cache for deterministic completions. The gateway only offers it keys
for temperature-0, tool-free calls, so a hit is always a faithful replay.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.llm.domain.chat import ChatResponse

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisResponseCache:
    def __init__(self, redis: Redis, *, ttl_seconds: int = 3600) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get(self, key: str) -> ChatResponse | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            return ChatResponse.model_validate_json(raw)
        except ValueError:
            return None  # a stale/corrupt entry is a miss, never an error

    async def put(self, key: str, response: ChatResponse) -> None:
        await self._redis.set(key, response.model_dump_json(), ex=self._ttl)
