"""Composition root: the only module that constructs infrastructure adapters.

Contract: interface layers (api, workers) obtain their dependencies from here;
nothing else instantiates engines/clients. As bounded contexts land in later
milestones, this grows into per-process wiring of ports to adapters — the
factory-function shape is deliberate so that growth is additive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

if TYPE_CHECKING:
    from spidey.platform.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    """Async SQLAlchemy engine; pre-ping keeps pooled connections honest."""
    return create_async_engine(
        settings.database_dsn,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


def create_redis_client(settings: Settings) -> aioredis.Redis:
    return aioredis.Redis.from_url(  # pyright: ignore[reportUnknownMemberType]
        settings.redis_dsn,
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )


def create_http_client() -> httpx.AsyncClient:
    """Outbound HTTP client for infrastructure probes (never for user URLs)."""
    return httpx.AsyncClient(timeout=httpx.Timeout(5.0), follow_redirects=False)
