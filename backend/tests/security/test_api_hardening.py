"""Attack-shaped tests for the API edge (docs/11 layers 1-3, SEC-WEB).

These tests assert the *absence* of information leaks and the *presence* of
hardening headers — they exist to fail loudly if someone weakens the edge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from spidey.api.main import create_app
from spidey.platform.errors import NotFoundError
from tests.conftest import make_settings, stub_app_state

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest.fixture
def hardened_app() -> FastAPI:
    """App with a deliberately exploding route and a domain-error route."""
    app = create_app(make_settings())

    async def boom() -> None:
        secret = "kaboom-internal-detail"  # must never reach a client
        raise RuntimeError(secret)

    async def missing() -> None:
        raise NotFoundError("run 42 does not exist")

    app.add_api_route("/api/v1/_test/boom", boom, methods=["GET"])
    app.add_api_route("/api/v1/_test/missing", missing, methods=["GET"])
    stub_app_state(app)
    return app


@pytest.fixture
async def hardened_client(hardened_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=hardened_app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


class TestSecurityHeaders:
    async def test_hardening_headers_on_success(self, hardened_client: httpx.AsyncClient) -> None:
        response = await hardened_client.get("/api/v1/health/live")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Cache-Control"] == "no-store"
        assert "default-src 'none'" in response.headers["Content-Security-Policy"]

    async def test_hardening_headers_survive_a_500(
        self, hardened_client: httpx.AsyncClient
    ) -> None:
        response = await hardened_client.get("/api/v1/_test/boom")
        assert response.status_code == 500
        assert response.headers["X-Content-Type-Options"] == "nosniff"


class TestErrorLeakage:
    async def test_unhandled_exception_leaks_nothing(
        self, hardened_client: httpx.AsyncClient
    ) -> None:
        response = await hardened_client.get("/api/v1/_test/boom")
        assert response.status_code == 500
        assert response.headers["content-type"].startswith("application/problem+json")
        body = response.text
        assert "kaboom-internal-detail" not in body
        assert "RuntimeError" not in body
        assert "Traceback" not in body
        assert response.json()["type"] == "urn:spidey:error:internal-error"

    async def test_domain_error_renders_problem(self, hardened_client: httpx.AsyncClient) -> None:
        response = await hardened_client.get("/api/v1/_test/missing")
        assert response.status_code == 404
        problem = response.json()
        assert problem["type"] == "urn:spidey:error:not-found"
        assert problem["detail"] == "run 42 does not exist"
        assert problem["instance"] == "/api/v1/_test/missing"

    async def test_validation_error_shape_is_bounded(
        self, hardened_client: httpx.AsyncClient
    ) -> None:
        response = await hardened_client.post("/api/v1/_test/missing")  # wrong method
        assert response.status_code == 405  # no stack, standard problem-free 405


class TestRequestIdHygiene:
    async def test_valid_incoming_id_is_echoed(self, hardened_client: httpx.AsyncClient) -> None:
        response = await hardened_client.get(
            "/api/v1/health/live", headers={"X-Request-ID": "abc12345-safe-id"}
        )
        assert response.headers["X-Request-ID"] == "abc12345-safe-id"

    async def test_log_injection_shaped_id_is_replaced(
        self, hardened_client: httpx.AsyncClient
    ) -> None:
        hostile = 'x" level=error injected\n{"fake":"log"}'
        response = await hardened_client.get(
            "/api/v1/health/live", headers={"X-Request-ID": hostile}
        )
        issued = response.headers["X-Request-ID"]
        assert issued != hostile
        assert len(issued) == 32  # fresh uuid4 hex

    async def test_oversized_id_is_replaced(self, hardened_client: httpx.AsyncClient) -> None:
        response = await hardened_client.get(
            "/api/v1/health/live", headers={"X-Request-ID": "a" * 300}
        )
        assert len(response.headers["X-Request-ID"]) == 32


class TestCors:
    async def test_disallowed_origin_gets_no_cors_headers(
        self, hardened_client: httpx.AsyncClient
    ) -> None:
        response = await hardened_client.get(
            "/api/v1/health/live", headers={"Origin": "https://evil.example"}
        )
        assert "access-control-allow-origin" not in response.headers

    async def test_allowed_origin_is_reflected(self) -> None:
        app = create_app(make_settings(cors_origins="https://app.example.com"))
        stub_app_state(app)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/v1/health/live", headers={"Origin": "https://app.example.com"}
            )
        assert response.headers["access-control-allow-origin"] == "https://app.example.com"
