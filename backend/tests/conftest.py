"""Shared fixtures. Environment defaults are set before any spidey import so
Settings always validates; tests that need different values construct Settings
explicitly or use monkeypatch."""

from __future__ import annotations

import os
import socket

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

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from spidey.api.main import create_app
from spidey.platform.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI


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
