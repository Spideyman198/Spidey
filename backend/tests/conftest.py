"""Shared fixtures. Environment defaults are set before any spidey import so
Settings always validates; tests that need different values construct Settings
explicitly or use monkeypatch."""

from __future__ import annotations

import os
import pathlib
import socket
import tempfile

# Must run before importing spidey modules (Settings reads env at import sites).
# 127.0.0.1, never "localhost": on Windows hosts, localhost can resolve to ::1
# where Docker Desktop's port proxy accepts the TCP handshake but routes
# nowhere — protocol handshakes then hang until timeout.
# Defaults target the local compose dev stack (see .env.example) so integration
# tests run out of the box when it is up and skip when it is down; CI overrides
# all of these with its own service credentials at the job level.
os.environ.setdefault("SPIDEY_ENVIRONMENT", "test")
os.environ.setdefault(
    "SPIDEY_DATABASE_URL",
    "postgresql+asyncpg://spidey:spidey-dev-password@127.0.0.1:5432/spidey",
)
os.environ.setdefault("SPIDEY_REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("SPIDEY_QDRANT_URL", "http://127.0.0.1:6333")
os.environ.setdefault(
    "SPIDEY_AUTH_SECRET_KEY", "test-secret-key-at-least-thirty-two-characters-long"
)
os.environ.setdefault(
    "SPIDEY_ENCRYPTION_MASTER_KEY", "test-encryption-master-key-thirty-two-chars-x"
)
# A writable workspaces root for integration tests (the default /var/lib path
# is not writable on the Windows dev host).
os.environ.setdefault(
    "SPIDEY_WORKSPACES_ROOT",
    str(pathlib.Path(tempfile.gettempdir()) / "spidey-test-workspaces"),
)

import uuid
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from asgi_lifespan import LifespanManager

from spidey.api.main import create_app
from spidey.platform.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI

    from spidey.composition import Container


def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@spidey.dev"


def app_container(client: httpx.AsyncClient) -> Container:
    """Typed accessor for the wired container behind an ASGI test client.

    Reaching the app through ``_transport`` is the supported test idiom for
    httpx's ASGITransport; there is no public accessor."""
    transport = cast("httpx.ASGITransport", client._transport)  # pyright: ignore[reportPrivateUsage]
    app = cast("FastAPI", transport.app)
    return cast("Container", app.state.container)


def make_settings(**overrides: Any) -> Settings:
    """Fresh Settings from the test environment plus explicit overrides."""
    return Settings(_env_file=None, **overrides)  # pyright: ignore[reportCallIssue]


def service_reachable(host: str, port: int, timeout: float = 0.5) -> bool:
    """True when a TCP connect succeeds — used to auto-skip integration tests."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client against the app without lifespan (unit tests stub app.state)."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


# ── Fakes for readiness checks ────────────────────────────────────────────────


class FakeConnection:
    async def execute(self, _query: object) -> None:
        return None

    async def __aenter__(self) -> FakeConnection:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeEngine:
    """Stands in for AsyncEngine in readiness tests."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    def connect(self) -> FakeConnection:
        if self._fail:
            msg = "connection refused"
            raise ConnectionError(msg)
        return FakeConnection()


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    async def ping(self) -> bool:
        if self._fail:
            msg = "connection refused"
            raise ConnectionError(msg)
        return True


class FakeHttpResponse:
    def __init__(self, *, ok: bool) -> None:
        self._ok = ok

    def raise_for_status(self) -> None:
        if not self._ok:
            msg = "503"
            raise RuntimeError(msg)


class FakeHttpClient:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    async def get(self, _url: str) -> FakeHttpResponse:
        if self._fail:
            msg = "connection refused"
            raise ConnectionError(msg)
        return FakeHttpResponse(ok=True)


def stub_app_state(
    app: FastAPI, *, db_ok: bool = True, redis_ok: bool = True, qdrant_ok: bool = True
) -> None:
    app.state.database_engine = FakeEngine(fail=not db_ok)
    app.state.redis_client = FakeRedis(fail=not redis_ok)
    app.state.http_client = FakeHttpClient(fail=not qdrant_ok)
    app.state.qdrant_endpoint = "http://qdrant.invalid:6333"


# ── Live-stack fixtures (integration + security), shared across test dirs ──────


# Integration tests reset the schema, so they run against a DEDICATED database
# (never the dev DB) — deriving its URL by swapping the database name to
# ``<db>_test``. CI already provisions ``spidey_test``; locally it is created on
# first use (see `_ensure_test_database`).
def _test_database_url() -> str:
    base = make_settings()
    url = base.database_url
    name = (url.path or "/spidey").lstrip("/")
    test_name = name if name.endswith("_test") else f"{name}_test"
    return str(url).rsplit("/", 1)[0] + f"/{test_name}"


_LIVE_SETTINGS = make_settings(
    auth_secret_key="integration-test-secret-key-at-least-32-chars",
    database_url=_test_database_url(),
)


async def _ensure_test_database() -> None:
    """Create the dedicated test database if it does not exist (idempotent).

    Connects to the default ``postgres`` maintenance DB with autocommit, since
    CREATE DATABASE cannot run inside a transaction.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    url = _LIVE_SETTINGS.database_url
    target = (url.path or "").lstrip("/")
    admin_url = str(url).rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            from sqlalchemy import text as _text

            exists = await conn.scalar(
                _text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target}
            )
            if not exists:
                await conn.execute(_text(f'CREATE DATABASE "{target}"'))
    finally:
        await engine.dispose()


# asyncpg rejects multiple statements in one execute() (prepared-statement
# protocol), so each DDL statement is issued separately.
_AUDIT_TRIGGER_STATEMENTS = (
    """
    CREATE OR REPLACE FUNCTION spidey_forbid_mutation() RETURNS TRIGGER AS $$
    BEGIN RAISE EXCEPTION 'audit_log is append-only: % is not permitted', TG_OP; END;
    $$ LANGUAGE plpgsql;
    """,
    """
    CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION spidey_forbid_mutation();
    """,
)


def live_settings() -> Settings:
    return _LIVE_SETTINGS


@pytest.fixture
async def app_client() -> AsyncIterator[httpx.AsyncClient]:
    """Fully wired app on a freshly reset schema with a flushed Redis DB.

    Skips when the compose stack is unreachable, so unit runs stay green.
    """
    import importlib

    from sqlalchemy import text

    from spidey.composition import build_container
    from spidey.platform.db import Base

    # Register every context's models on the shared metadata before create_all.
    for module in (
        "spidey.platform.audit",
        "spidey.identity.infrastructure.orm",
        "spidey.memory.infrastructure.orm",
    ):
        importlib.import_module(module)

    if not (service_reachable("127.0.0.1", 5432) and service_reachable("127.0.0.1", 6379)):
        pytest.skip("Postgres/Redis not reachable — start the compose stack")

    await _ensure_test_database()
    container = build_container(_LIVE_SETTINGS)
    async with container.engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
        for statement in _AUDIT_TRIGGER_STATEMENTS:
            await conn.execute(text(statement))
    await container.redis.flushdb()
    await container.engine.dispose()
    await container.redis.aclose()

    from spidey.api.main import create_app as _create_app

    app = _create_app(_LIVE_SETTINGS)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            yield http


async def bootstrap_admin(client: httpx.AsyncClient, email: str = "admin@spidey.dev") -> str:
    """Create the first admin through the app's own container (shared schema)
    and return an access token. Shared by integration and security tests."""
    from spidey.identity.application import UserService
    from spidey.identity.infrastructure import Argon2PasswordHasher
    from spidey.identity.infrastructure.repositories import (
        PostgresRefreshTokenRepository,
        PostgresUserRepository,
    )
    from spidey.platform.audit import AuditLogger

    async with app_container(client).session_factory() as session:
        service = UserService(
            users=PostgresUserRepository(session),
            refresh_tokens=PostgresRefreshTokenRepository(session),
            hasher=Argon2PasswordHasher(),
            audit=AuditLogger(session),
        )
        await service.bootstrap_admin(email=email, password="AdminPass123!")
        await session.commit()

    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "AdminPass123!"}
    )
    return response.json()["access_token"]
