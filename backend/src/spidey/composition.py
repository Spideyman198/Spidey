"""Composition root: the only module that constructs infrastructure adapters.

Contract: interface layers (api, workers) obtain their dependencies from here;
nothing else instantiates engines/clients. Process-lifetime singletons
(engine, redis, hasher, token issuer) are built once at startup and held on
app state; request-scoped services (repositories, use cases bound to a DB
session) are assembled per request in ``api/deps.py`` from these singletons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from spidey.codeintel.infrastructure import TreeSitterParser
from spidey.identity.infrastructure import (
    Argon2PasswordHasher,
    JwtTokenIssuer,
    RedisLockoutStore,
    RedisRateLimiter,
)
from spidey.platform.db import create_session_factory
from spidey.platform.security import SecretCipher
from spidey.platform.tasks import CeleryTaskQueue
from spidey.workspaces.infrastructure import GitPythonProvider, LocalWorkspaceStorage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from spidey.codeintel.domain.ports import Parser
    from spidey.identity.domain.ports import (
        LockoutStore,
        PasswordHasher,
        RateLimiter,
        TokenIssuer,
    )
    from spidey.platform.config import Settings
    from spidey.platform.tasks import TaskQueue
    from spidey.workspaces.domain.ports import GitProvider, WorkspaceStorage


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


@dataclass(frozen=True)
class Container:
    """Process-lifetime singletons shared across requests."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: aioredis.Redis
    http_client: httpx.AsyncClient
    qdrant_endpoint: str
    hasher: PasswordHasher
    token_issuer: TokenIssuer
    rate_limiter: RateLimiter
    lockouts: LockoutStore
    cipher: SecretCipher
    workspace_storage: WorkspaceStorage
    git_provider: GitProvider
    task_queue: TaskQueue
    code_parser: Parser


def build_container(settings: Settings) -> Container:
    """Construct all process-lifetime singletons. Called once at startup."""
    engine = create_database_engine(settings)
    redis = create_redis_client(settings)
    return Container(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        redis=redis,
        http_client=create_http_client(),
        qdrant_endpoint=settings.qdrant_endpoint,
        hasher=Argon2PasswordHasher(),
        token_issuer=JwtTokenIssuer(
            secret=settings.auth_secret_key.get_secret_value(),
            ttl_seconds=settings.access_token_ttl_seconds,
        ),
        rate_limiter=RedisRateLimiter(redis),
        lockouts=RedisLockoutStore(redis),
        cipher=SecretCipher(settings.encryption_master_key.get_secret_value()),
        workspace_storage=LocalWorkspaceStorage(settings),
        git_provider=GitPythonProvider(settings),
        task_queue=CeleryTaskQueue(settings),
        code_parser=TreeSitterParser(),
    )


async def close_container(container: Container) -> None:
    await container.http_client.aclose()
    await container.redis.aclose()
    await container.engine.dispose()
