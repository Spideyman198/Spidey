"""Redis-backed abuse guards: atomic token bucket and account lockout.

Fail-closed contract: Redis unavailability raises ``ServiceUnavailableError``
(the auth path aborts) rather than silently skipping a security check.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

from redis.exceptions import RedisError

from spidey.platform.errors import ServiceUnavailableError

if TYPE_CHECKING:
    import redis.asyncio as aioredis

# Atomic token bucket. KEYS[1]=bucket, ARGV: capacity, refill/sec, now_ms, ttl_ms.
_TOKEN_BUCKET_LUA = """
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity ; ts = now end
tokens = math.min(capacity, tokens + (math.max(0, now - ts) / 1000.0) * refill)
local allowed = 0
if tokens >= 1 then tokens = tokens - 1 ; allowed = 1 end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', KEYS[1], ARGV[4])
return allowed
"""


class RedisRateLimiter:
    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client
        self._script = client.register_script(_TOKEN_BUCKET_LUA)

    async def acquire(self, key: str, *, capacity: int, refill_per_second: float) -> bool:
        # TTL: time to fully refill an empty bucket, so idle keys expire.
        ttl_ms = int((capacity / refill_per_second) * 1000) + 60_000
        try:
            # The script returns 1/0; redis-py types the call as Any.
            allowed = cast(
                "int",
                await self._script(
                    keys=[f"rl:{key}"],
                    args=[capacity, refill_per_second, int(time.time() * 1000), ttl_ms],
                ),
            )
        except RedisError as exc:
            raise ServiceUnavailableError("rate limiter unavailable") from exc
        return allowed == 1


class RedisLockoutStore:
    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client

    async def is_locked(self, key: str) -> bool:
        try:
            return bool(await self._client.exists(f"lockout:{key}"))
        except RedisError as exc:
            raise ServiceUnavailableError("lockout store unavailable") from exc

    async def register_failure(self, key: str, *, threshold: int, lock_seconds: int) -> int:
        try:
            failures = int(await self._client.incr(f"lockout-fail:{key}"))
            # Failure streak decays on the lockout horizon.
            await self._client.expire(f"lockout-fail:{key}", lock_seconds)
            if failures >= threshold:
                await self._client.set(f"lockout:{key}", "1", ex=lock_seconds)
                await self._client.delete(f"lockout-fail:{key}")
        except RedisError as exc:
            raise ServiceUnavailableError("lockout store unavailable") from exc
        return failures

    async def reset(self, key: str) -> None:
        try:
            await self._client.delete(f"lockout-fail:{key}", f"lockout:{key}")
        except RedisError as exc:
            raise ServiceUnavailableError("lockout store unavailable") from exc
