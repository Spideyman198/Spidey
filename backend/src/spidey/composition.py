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
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from spidey.codeintel.infrastructure import QdrantVectorIndex, TreeSitterParser
from spidey.execution.infrastructure import DockerSandbox
from spidey.identity.infrastructure import (
    Argon2PasswordHasher,
    JwtTokenIssuer,
    RedisLockoutStore,
    RedisRateLimiter,
)
from spidey.llm.application import ProviderRegistry
from spidey.llm.domain import ModelRef, ProviderName, Role, RouteConfig
from spidey.llm.infrastructure import (
    AnthropicFactory,
    FastembedDenseEmbedder,
    FastembedSparseEmbedder,
    GeminiFactory,
    OpenAiCompatibleFactory,
    RedisBudgetLedger,
    RedisResponseCache,
)
from spidey.memory.infrastructure import QdrantMemoryIndex
from spidey.platform.db import create_session_factory
from spidey.platform.events import StreamBus
from spidey.platform.security import SecretCipher
from spidey.platform.tasks import CeleryTaskQueue
from spidey.workspaces.infrastructure import (
    GitHubPrProvider,
    GitPythonProvider,
    LocalWorkspaceStorage,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from spidey.codeintel.domain.ports import (
        DenseEmbedder,
        Parser,
        SparseEmbedder,
        VectorIndex,
    )
    from spidey.execution.domain import Sandbox
    from spidey.identity.domain.ports import (
        LockoutStore,
        PasswordHasher,
        RateLimiter,
        TokenIssuer,
    )
    from spidey.llm.application.registry import ChatModelFactory
    from spidey.llm.domain.ports import BudgetLedger, ResponseCache
    from spidey.platform.config import RouteSetting, Settings
    from spidey.platform.tasks import TaskQueue
    from spidey.workspaces.domain.ports import GitProvider, PrProvider, WorkspaceStorage


def build_provider_registry(settings: Settings) -> ProviderRegistry:
    """Assemble the provider registry from config: a factory per provider that has
    credentials, and the role→route table (ADR-0012)."""
    factories: dict[ProviderName, ChatModelFactory] = {}
    if settings.anthropic_api_key is not None:
        factories[ProviderName.ANTHROPIC] = AnthropicFactory(
            api_key=settings.anthropic_api_key.get_secret_value()
        )
    if settings.openai_api_key is not None:
        factories[ProviderName.OPENAI_COMPATIBLE] = OpenAiCompatibleFactory(
            api_key=settings.openai_api_key.get_secret_value(),
            base_url=settings.openai_base_url,
        )
    if settings.gemini_api_key is not None:
        factories[ProviderName.GEMINI] = GeminiFactory(
            api_key=settings.gemini_api_key.get_secret_value()
        )
    routes = {Role(role): _to_route(rs) for role, rs in settings.llm_routes.items()}
    return ProviderRegistry(factories=factories, routes=routes)


def _to_route(setting: RouteSetting) -> RouteConfig:
    return RouteConfig(
        provider=ProviderName(setting.provider),
        model=setting.model,
        max_tokens=setting.max_tokens,
        temperature=setting.temperature,
        fallbacks=[
            ModelRef(provider=ProviderName(ref.provider), model=ref.model)
            for ref in setting.fallbacks
        ],
    )


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


def create_qdrant_client(settings: Settings) -> AsyncQdrantClient:
    # check_compatibility=False: the pinned client is newer than some deployed
    # server builds; the REST surface we use (named vectors, RRF fusion) is
    # stable across the skew, so we opt out of the startup version handshake.
    return AsyncQdrantClient(url=settings.qdrant_endpoint, check_compatibility=False)


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
    pr_provider: PrProvider
    task_queue: TaskQueue
    code_parser: Parser
    dense_embedder: DenseEmbedder
    sparse_embedder: SparseEmbedder
    qdrant_client: AsyncQdrantClient
    vector_index: VectorIndex
    stream_bus: StreamBus
    llm_registry: ProviderRegistry
    response_cache: ResponseCache
    budget_ledger: BudgetLedger
    sandbox: Sandbox
    memory_vector_index: QdrantMemoryIndex


def build_container(settings: Settings) -> Container:
    """Construct all process-lifetime singletons. Called once at startup."""
    engine = create_database_engine(settings)
    redis = create_redis_client(settings)
    qdrant_client = create_qdrant_client(settings)
    # fastembed models are loaded eagerly (and reused for the process lifetime);
    # in production they are baked into the image so this is a local, no-network
    # load. Switching the dense model changes the vector dimension → re-index.
    cache_dir = str(settings.fastembed_cache_path) if settings.fastembed_cache_path else None
    dense_embedder = FastembedDenseEmbedder(
        model_name=settings.embedding_model,
        dimension=settings.embedding_dim,
        cache_dir=cache_dir,
    )
    sparse_embedder = FastembedSparseEmbedder(
        model_name=settings.sparse_embedding_model,
        cache_dir=cache_dir,
    )
    http_client = create_http_client()
    return Container(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        redis=redis,
        http_client=http_client,
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
        pr_provider=GitHubPrProvider(http_client),
        task_queue=CeleryTaskQueue(settings),
        code_parser=TreeSitterParser(),
        dense_embedder=dense_embedder,
        sparse_embedder=sparse_embedder,
        qdrant_client=qdrant_client,
        vector_index=QdrantVectorIndex(
            client=qdrant_client,
            collection_prefix=settings.qdrant_collection_prefix,
            dense_dim=settings.embedding_dim,
        ),
        stream_bus=StreamBus(redis),
        llm_registry=build_provider_registry(settings),
        response_cache=RedisResponseCache(redis, ttl_seconds=settings.llm_cache_ttl_seconds),
        budget_ledger=RedisBudgetLedger(
            redis,
            max_tokens=settings.llm_budget_max_tokens,
            max_cost_usd=settings.llm_budget_max_cost_usd,
            window_seconds=settings.llm_budget_window_seconds,
        ),
        sandbox=DockerSandbox(
            image=settings.sandbox_image,
            run_uid=settings.sandbox_run_uid,
            egress_proxy_network=settings.sandbox_egress_network,
        ),
        memory_vector_index=QdrantMemoryIndex(
            client=qdrant_client, dense_dim=settings.embedding_dim
        ),
    )


async def close_container(container: Container) -> None:
    await container.http_client.aclose()
    await container.redis.aclose()
    await container.qdrant_client.close()
    await container.engine.dispose()
