"""Integration tests against real Postgres/Redis (CI services or local stack).

Auto-skip when services are unreachable so `make test` stays green on a laptop
without Docker; CI always provides the services, so these always run there.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx
import pytest
from asgi_lifespan import LifespanManager

from spidey.api.main import create_app
from tests.conftest import make_settings, service_reachable


def _host_port(env_var: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(os.environ[env_var].replace("postgresql+asyncpg", "postgresql"))
    return parsed.hostname or "localhost", parsed.port or default_port


_pg_host, _pg_port = _host_port("SPIDEY_DATABASE_URL", 5432)
_redis_host, _redis_port = _host_port("SPIDEY_REDIS_URL", 6379)

requires_services = pytest.mark.skipif(
    not (service_reachable(_pg_host, _pg_port) and service_reachable(_redis_host, _redis_port)),
    reason="Postgres/Redis not reachable — start the compose stack to run integration tests",
)


@pytest.mark.integration
@requires_services
class TestRunningStack:
    async def test_lifespan_and_readiness_against_real_services(self) -> None:
        app = create_app(make_settings())
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get("/api/v1/health/ready")

        body = response.json()
        # Qdrant may legitimately be absent (e.g. CI services): degraded is fine,
        # but the critical components must be genuinely up.
        assert body["components"]["database"]["status"] == "ok"
        assert body["components"]["redis"]["status"] == "ok"
        assert body["status"] in {"ok", "degraded"}
        assert response.status_code == 200


class TestLifespanWithoutServices:
    async def test_clients_construct_and_dispose_lazily(self) -> None:
        """Lifespan never eagerly connects — startup must not depend on backing
        services being up (readiness reports that instead)."""
        app = create_app(make_settings())
        async with LifespanManager(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get("/api/v1/health/live")
        assert response.status_code == 200
