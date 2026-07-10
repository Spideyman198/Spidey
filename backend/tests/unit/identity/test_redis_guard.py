"""Redis guards fail closed: unavailability raises, never silently allows."""

from __future__ import annotations

import pytest
from redis.exceptions import RedisError

from spidey.identity.infrastructure import RedisLockoutStore, RedisRateLimiter
from spidey.platform.errors import ServiceUnavailableError


class _BrokenScript:
    async def __call__(self, *, keys: list[str], args: list[object]) -> int:
        raise RedisError("redis down")


class _BrokenRedis:
    def register_script(self, _script: str) -> _BrokenScript:
        return _BrokenScript()

    async def exists(self, *_: str) -> int:
        raise RedisError("redis down")

    async def incr(self, _key: str) -> int:
        raise RedisError("redis down")

    async def expire(self, _key: str, _seconds: int) -> bool:
        raise RedisError("redis down")

    async def set(self, *_: object, **__: object) -> bool:
        raise RedisError("redis down")

    async def delete(self, *_: str) -> int:
        raise RedisError("redis down")


class TestFailClosed:
    async def test_rate_limiter_unavailable_raises(self) -> None:
        limiter = RedisRateLimiter(_BrokenRedis())  # type: ignore[arg-type]
        with pytest.raises(ServiceUnavailableError):
            await limiter.acquire("k", capacity=10, refill_per_second=1.0)

    async def test_lockout_is_locked_unavailable_raises(self) -> None:
        store = RedisLockoutStore(_BrokenRedis())  # type: ignore[arg-type]
        with pytest.raises(ServiceUnavailableError):
            await store.is_locked("k")

    async def test_lockout_register_failure_unavailable_raises(self) -> None:
        store = RedisLockoutStore(_BrokenRedis())  # type: ignore[arg-type]
        with pytest.raises(ServiceUnavailableError):
            await store.register_failure("k", threshold=5, lock_seconds=900)

    async def test_lockout_reset_unavailable_raises(self) -> None:
        store = RedisLockoutStore(_BrokenRedis())  # type: ignore[arg-type]
        with pytest.raises(ServiceUnavailableError):
            await store.reset("k")
