"""Health endpoints: liveness is unconditional; readiness encodes NFR-1."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.conftest import stub_app_state

if TYPE_CHECKING:
    import httpx
    from fastapi import FastAPI


class TestLiveness:
    async def test_live_is_unconditional(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestReadiness:
    async def test_all_healthy(self, app: FastAPI, client: httpx.AsyncClient) -> None:
        stub_app_state(app)
        response = await client.get("/api/v1/health/ready")
        body = response.json()
        assert response.status_code == 200
        assert body["status"] == "ok"
        assert {name: c["status"] for name, c in body["components"].items()} == {
            "database": "ok",
            "redis": "ok",
            "qdrant": "ok",
        }

    async def test_database_down_is_unavailable(
        self, app: FastAPI, client: httpx.AsyncClient
    ) -> None:
        stub_app_state(app, db_ok=False)
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"

    async def test_redis_down_is_unavailable(self, app: FastAPI, client: httpx.AsyncClient) -> None:
        stub_app_state(app, redis_ok=False)
        response = await client.get("/api/v1/health/ready")
        assert response.status_code == 503

    async def test_qdrant_down_degrades_but_stays_ready(
        self, app: FastAPI, client: httpx.AsyncClient
    ) -> None:
        stub_app_state(app, qdrant_ok=False)
        response = await client.get("/api/v1/health/ready")
        body = response.json()
        assert response.status_code == 200  # NFR-1: search degrades, core serves
        assert body["status"] == "degraded"
        assert body["components"]["qdrant"]["status"] == "down"

    async def test_component_errors_expose_class_name_only(
        self, app: FastAPI, client: httpx.AsyncClient
    ) -> None:
        stub_app_state(app, db_ok=False)
        body = (await client.get("/api/v1/health/ready")).json()
        assert body["components"]["database"]["error"] == "ConnectionError"
        assert "refused" not in str(body)  # no messages, hosts, or DSNs


class TestObservabilitySurface:
    async def test_metrics_endpoint_exposes_http_metrics(
        self, app: FastAPI, client: httpx.AsyncClient
    ) -> None:
        stub_app_state(app)
        await client.get("/api/v1/health/live")
        response = await client.get("/metrics/")
        assert response.status_code == 200
        assert "spidey_http_requests_total" in response.text

    async def test_openapi_spec_served(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/v1/openapi.json")
        assert response.status_code == 200
        assert response.json()["info"]["title"] == "Spidey API"
