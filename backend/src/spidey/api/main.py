"""FastAPI application factory.

Middleware order (outermost first at runtime): request context → metrics →
security headers → CORS. Exception handlers translate everything to
RFC 9457 problems. Infrastructure clients live on ``app.state`` for the app's
lifetime and are the only stateful members of the process.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI
from prometheus_client import (
    make_asgi_app,  # pyright: ignore[reportUnknownVariableType] — untyped factory, cast at use
)
from starlette.middleware.cors import CORSMiddleware

import spidey
from spidey.api.errors import register_exception_handlers
from spidey.api.middleware import (
    MetricsMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from spidey.api.v1 import router as v1_router
from spidey.composition import create_database_engine, create_http_client, create_redis_client
from spidey.platform.config import Settings, get_settings
from spidey.platform.logging import configure_logging, get_logger
from spidey.platform.telemetry import instrument_fastapi, setup_tracing

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.types import ASGIApp

_logger = get_logger("spidey.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    configure_logging(settings)
    setup_tracing(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.database_engine = create_database_engine(settings)
        app.state.redis_client = create_redis_client(settings)
        app.state.http_client = create_http_client()
        app.state.qdrant_endpoint = settings.qdrant_endpoint
        _logger.info(
            "api_started", environment=settings.environment.value, version=spidey.__version__
        )
        try:
            yield
        finally:
            await app.state.http_client.aclose()
            await app.state.redis_client.aclose()
            await app.state.database_engine.dispose()
            _logger.info("api_stopped")

    app = FastAPI(
        title="Spidey API",
        version=spidey.__version__,
        summary="Autonomous coding agent platform",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # Starlette wraps last-added outermost: add in reverse of desired runtime order.
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(v1_router)
    # prometheus_client's ASGI factory is untyped; the runtime object is a valid ASGI app.
    app.mount("/metrics", cast("ASGIApp", make_asgi_app()))

    instrument_fastapi(app)
    return app
