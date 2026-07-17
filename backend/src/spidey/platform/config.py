"""Application configuration.

Contract: all configuration comes from the environment (12-factor), validated
once at startup. A missing or invalid required variable fails the process
immediately with a readable error — the application never runs half-configured.
No configuration value is ever hardcoded elsewhere in the codebase; every
consumer receives a :class:`Settings` instance.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ModelRefSetting(BaseModel):
    """A (provider, model) reference in the routing table. ``provider`` matches an
    ``llm`` ProviderName value; the composition root resolves it to an adapter."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str


class RouteSetting(ModelRefSetting):
    """One role's route: primary (provider, model) + params + fallback chain."""

    max_tokens: int = 1024
    temperature: float = 0.0
    fallbacks: list[ModelRefSetting] = Field(default_factory=list[ModelRefSetting])


def _default_routes() -> dict[str, RouteSetting]:
    frontier = "claude-sonnet-5"
    cheap = ModelRefSetting(provider="openai_compatible", model="gpt-4o-mini")
    return {
        "planner": RouteSetting(provider="anthropic", model=frontier),
        "coder": RouteSetting(provider="anthropic", model=frontier),
        "reviewer": RouteSetting(provider="anthropic", model=frontier),
        "summarizer": RouteSetting(
            provider="anthropic", model="claude-haiku-4-5-20251001", fallbacks=[cheap]
        ),
        "chat": RouteSetting(
            provider="anthropic", model="claude-haiku-4-5-20251001", fallbacks=[cheap]
        ),
    }


class Settings(BaseSettings):
    """Validated runtime configuration. See ``.env.example`` for documentation."""

    model_config = SettingsConfigDict(
        env_prefix="SPIDEY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = Environment.DEV
    log_level: LogLevel = LogLevel.INFO

    database_url: PostgresDsn
    redis_url: RedisDsn
    qdrant_url: AnyHttpUrl

    # ── Authentication (identity context) ────────────────────────────────────
    # HS256 signing key for access tokens. Required, never defaulted, never
    # logged (SecretStr). 32+ chars enforced — a short key defeats HMAC.
    auth_secret_key: SecretStr = Field(min_length=32)
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_days: int = Field(default=14, ge=1, le=90)

    # ── Secret encryption (workspaces context) ───────────────────────────────
    # Master key for envelope-encrypting user secrets (GitHub PATs) at rest.
    # 32+ chars; a key-derivation step turns it into a 256-bit AES key.
    encryption_master_key: SecretStr = Field(min_length=32)

    # ── Workspaces & ingestion ───────────────────────────────────────────────
    # Base directory that holds every workspace's isolated tree. Each workspace
    # lives in a subdirectory and no file access may escape its root (SEC-FS).
    workspaces_root: Path = Field(default=Path("/var/lib/spidey/workspaces"))
    # Per-workspace disk quota (bytes). Default 2 GiB.
    workspace_max_bytes: int = Field(default=2 * 1024**3, ge=1024**2)
    # Files larger than this are inventoried but not read for indexing. 5 MiB.
    ingest_max_file_bytes: int = Field(default=5 * 1024**2, ge=1024)
    # Hosts a repository may be cloned from (SSRF allow-list).
    allowed_git_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["github.com"]
    )

    # ── Embeddings & vector search (codeintel / llm) ──────────────────────────
    # Local fastembed models: dense semantic + sparse BM25 (bundled/baked, no
    # runtime download in production images). Switching the dense model changes
    # the vector dimension, so it is a re-index event.
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5")
    embedding_dim: int = Field(default=384, ge=1)
    sparse_embedding_model: str = Field(default="Qdrant/bm25")
    embedding_batch_size: int = Field(default=64, ge=1, le=512)
    # Directory holding pre-baked fastembed models (set in the container image).
    fastembed_cache_path: Path | None = Field(default=None)
    # Prefix for per-workspace Qdrant collections.
    qdrant_collection_prefix: str = Field(default="code")

    # ── Knowledge graph & graph-augmented retrieval (codeintel, M5) ────────────
    # Hard caps on graph traversals (ADR-0003) — a query can never exceed these.
    graph_query_max_depth: int = Field(default=6, ge=1, le=20)
    graph_query_max_results: int = Field(default=200, ge=1, le=2000)
    graph_query_default_depth: int = Field(default=3, ge=1, le=20)
    # Graph-augmented retrieval (docs/06): top hits are expanded through the
    # graph and the relationships emitted as structured facts. Feature-flagged —
    # the exit criterion is the retrieval eval showing expansion ≥ neutral.
    graph_expansion_enabled: bool = Field(default=True)
    graph_expansion_hops: int = Field(default=1, ge=1, le=3)
    # Max seed hits expanded and max facts emitted, to bound the added context.
    graph_expansion_seeds: int = Field(default=5, ge=1, le=50)
    graph_expansion_max_facts: int = Field(default=15, ge=1, le=100)

    # ── LLM gateway (llm context, M6) ─────────────────────────────────────────
    # Provider credentials. Absent → that provider is simply not registered; a
    # role routed only to it fails fast rather than degrading silently.
    anthropic_api_key: SecretStr | None = Field(default=None)
    openai_api_key: SecretStr | None = Field(default=None)
    # Base URL points the one OpenAI-compatible adapter at OpenAI, Ollama, vLLM,
    # or Azure (ADR-0012). None → the SDK default (OpenAI).
    openai_base_url: str | None = Field(default=None)
    gemini_api_key: SecretStr | None = Field(default=None)
    # Role → route table. Switching a role's provider is a config change only.
    llm_routes: dict[str, RouteSetting] = Field(default_factory=_default_routes)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    # Response cache (deterministic calls only) and per-scope budgets (NFR-5).
    llm_cache_ttl_seconds: int = Field(default=3600, ge=0)
    llm_budget_max_tokens: int = Field(default=2_000_000, ge=1)
    llm_budget_max_cost_usd: float = Field(default=25.0, gt=0)
    llm_budget_window_seconds: int = Field(default=86_400, ge=60)

    # ── Execution sandbox (execution context, M9) ─────────────────────────────
    # The hardened image DockerSandbox runs untrusted code in (ADR-0007). Pin by
    # digest in production. Every run is a fresh container with these ceilings.
    sandbox_image: str = Field(default="spidey-sandbox:latest")
    sandbox_run_uid: int = Field(default=65532, ge=1)
    sandbox_cpus: float = Field(default=1.0, gt=0, le=8)
    sandbox_memory_mb: int = Field(default=512, ge=64, le=8192)
    sandbox_pids: int = Field(default=256, ge=16, le=4096)
    sandbox_timeout_seconds: int = Field(default=120, ge=1, le=1800)
    sandbox_max_output_bytes: int = Field(default=1_000_000, ge=1024, le=16_000_000)
    # Pre-created allow-list-only docker network for approved installs; None →
    # even an approved network run stays offline (fail-closed).
    sandbox_egress_network: str | None = Field(default=None)
    # Pre-authorize network installs for a run (default off: each is a human gate).
    sandbox_allow_network_installs: bool = Field(default=False)

    otel_exporter_otlp_endpoint: AnyHttpUrl | None = None
    otel_service_name: str = Field(default="spidey", min_length=1)

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("otel_exporter_otlp_endpoint", mode="before")
    @classmethod
    def _empty_string_is_none(cls, value: object) -> object:
        # Compose passes "" when the observability profile is off.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cors_origins", "allowed_git_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _validate_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            if origin == "*":
                msg = "wildcard CORS origin is not permitted; list explicit origins"
                raise ValueError(msg)
            if not origin.startswith(("http://", "https://")):
                msg = f"CORS origin must be an absolute http(s) URL, got: {origin!r}"
                raise ValueError(msg)
        return origins

    @property
    def is_dev(self) -> bool:
        return self.environment is Environment.DEV

    @property
    def database_dsn(self) -> str:
        return str(self.database_url)

    @property
    def checkpointer_dsn(self) -> str:
        """Plain ``postgresql://`` DSN for the LangGraph checkpointer (psycopg),
        which does not use the SQLAlchemy ``+asyncpg`` driver suffix."""
        return str(self.database_url).replace("+asyncpg", "")

    @property
    def redis_dsn(self) -> str:
        return str(self.redis_url)

    @property
    def qdrant_endpoint(self) -> str:
        return str(self.qdrant_url).rstrip("/")

    @property
    def workspaces_root_path(self) -> Path:
        return self.workspaces_root


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache settings. Raises pydantic ``ValidationError`` on bad env."""
    return Settings()  # pyright: ignore[reportCallIssue] — fields come from env
