"""Run event streaming over SSE (ADR-0006, FR-6.1).

Reads a run's per-run Redis stream from a client cursor (``Last-Event-ID``), so a
refreshing browser or a restarted API resumes without loss. Client→server
actions stay ordinary REST posts; this channel is unidirectional by design.

Authorization: a run's owner is recorded in Redis when the run is created
(``set_run_owner``); a non-owner sees the run as not found. The scripted chat
(M6) and the agent runtime (M7) both create runs and stream here.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from spidey.api.deps import CurrentUser
from spidey.platform.errors import NotFoundError
from spidey.platform.events import stream_key_for

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from redis.asyncio import Redis

    from spidey.platform.events import StreamBus

router = APIRouter(prefix="/runs", tags=["runs"])

# Short server-side block so client disconnects are noticed promptly and a
# keep-alive comment is emitted through idle periods.
_BLOCK_MS = 2000
_READ_COUNT = 100
_OWNER_TTL_SECONDS = 24 * 3600


def _owner_key(run_id: uuid.UUID) -> str:
    return f"run:{run_id}:owner"


async def set_run_owner(redis: Redis, run_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    """Record who may stream a run (ephemeral, TTL-bounded)."""
    await redis.set(_owner_key(run_id), str(owner_id), ex=_OWNER_TTL_SECONDS)


@router.get(
    "/{run_id}/events",
    summary="Stream a run's events (SSE)",
    response_class=StreamingResponse,
)
async def stream_run_events(
    run_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    container = request.app.state.container
    owner = await container.redis.get(_owner_key(run_id))
    if owner != str(user.id):
        raise NotFoundError("run not found")

    bus: StreamBus = container.stream_bus
    stream_key = stream_key_for(run_id)
    # No cursor → replay the retained stream from the start; else resume after it.
    cursor = last_event_id or "0"

    async def events() -> AsyncIterator[str]:
        nonlocal cursor
        while not await request.is_disconnected():
            messages = await bus.read(
                stream_key, last_id=cursor, block_ms=_BLOCK_MS, count=_READ_COUNT
            )
            if not messages:
                yield ": keep-alive\n\n"
                continue
            for message_id, data in messages:
                cursor = message_id
                yield f"id: {message_id}\ndata: {data}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
