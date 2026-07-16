"""Redis token/cost budget ledger (BudgetLedger adapter, NFR-5).

Per-scope (session/run) rolling counters with a TTL window. ``would_exceed`` is a
pre-call guard against the requested ``max_tokens``; ``record`` accrues actual
usage + cost after the call. Enforced in the gateway, so no caller can bypass it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from spidey.llm.domain.chat import Usage

_PREFIX = "llm:budget:"


class RedisBudgetLedger:
    def __init__(
        self,
        redis: Redis,
        *,
        max_tokens: int,
        max_cost_usd: float,
        window_seconds: int,
    ) -> None:
        self._redis = redis
        self._max_tokens = max_tokens
        self._max_cost = max_cost_usd
        self._window = window_seconds

    async def would_exceed(self, scope: str, *, tokens: int) -> bool:
        used_tokens = int(await self._redis.get(self._key(scope, "tokens")) or 0)
        used_cost = float(await self._redis.get(self._key(scope, "cost")) or 0.0)
        return used_tokens + tokens > self._max_tokens or used_cost >= self._max_cost

    async def record(self, scope: str, *, usage: Usage, cost_usd: float) -> None:
        token_key = self._key(scope, "tokens")
        cost_key = self._key(scope, "cost")
        pipe = self._redis.pipeline()
        pipe.incrby(token_key, usage.total_tokens)
        pipe.expire(token_key, self._window)
        pipe.incrbyfloat(cost_key, cost_usd)
        pipe.expire(cost_key, self._window)
        await pipe.execute()

    @staticmethod
    def _key(scope: str, metric: str) -> str:
        return f"{_PREFIX}{scope}:{metric}"
