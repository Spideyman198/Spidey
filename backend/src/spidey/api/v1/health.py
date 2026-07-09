"""Liveness and readiness endpoints.

Contract (NFR-1 graceful degradation): Postgres and Redis are *critical* — the
platform cannot operate without them, so readiness returns 503 when either is
down. Qdrant is *degradable* — search features disable, core chat works — so a
Qdrant outage reports ``degraded`` with HTTP 200. Component errors expose the
exception class name only, never connection strings or hosts.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Coroutine

    import httpx
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import AsyncEngine

_logger = get_logger("spidey.api.health")

router = APIRouter(prefix="/health", tags=["health"])

_CHECK_TIMEOUT_SECONDS = 2.0

ComponentState = Literal["ok", "down"]
OverallState = Literal["ok", "degraded", "unavailable"]


class ComponentHealth(BaseModel):
    status: ComponentState
    latency_ms: float
    error: str | None = None


class ReadinessReport(BaseModel):
    status: OverallState
    components: dict[str, ComponentHealth]


class LivenessReport(BaseModel):
    status: Literal["ok"]


async def _run_check(coro: Coroutine[Any, Any, None]) -> ComponentHealth:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=_CHECK_TIMEOUT_SECONDS)
    except Exception as exc:
        return ComponentHealth(
            status="down",
            latency_ms=_elapsed_ms(started),
            error=type(exc).__name__,
        )
    return ComponentHealth(status="ok", latency_ms=_elapsed_ms(started))


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


async def _ping_database(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def _ping_redis(client: aioredis.Redis) -> None:
    await client.ping()  # pyright: ignore[reportUnknownMemberType, reportGeneralTypeIssues]


async def _ping_qdrant(client: httpx.AsyncClient, endpoint: str) -> None:
    response = await client.get(f"{endpoint}/readyz")
    response.raise_for_status()


@router.get("/live", summary="Liveness probe")
async def live() -> LivenessReport:
    """Process is up and serving. No dependency checks — restart decisions only."""
    return LivenessReport(status="ok")


@router.get(
    "/ready",
    summary="Readiness probe",
    responses={503: {"model": ReadinessReport, "description": "A critical dependency is down"}},
)
async def ready(request: Request, response: Response) -> ReadinessReport:
    """Dependency-checked readiness with per-component detail."""
    state = request.app.state
    database, redis_, qdrant = await asyncio.gather(
        _run_check(_ping_database(state.database_engine)),
        _run_check(_ping_redis(state.redis_client)),
        _run_check(_ping_qdrant(state.http_client, state.qdrant_endpoint)),
    )

    components = {"database": database, "redis": redis_, "qdrant": qdrant}
    critical_down = database.status == "down" or redis_.status == "down"

    status: OverallState
    if critical_down:
        status = "unavailable"
        response.status_code = 503
    elif qdrant.status == "down":
        status = "degraded"
    else:
        status = "ok"

    if status != "ok":
        _logger.warning(
            "readiness_degraded",
            status=status,
            components={name: c.status for name, c in components.items()},
        )
    return ReadinessReport(status=status, components=components)
