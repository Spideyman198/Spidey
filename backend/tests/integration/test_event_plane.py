"""Event plane end-to-end against live Postgres + Redis (M6, docs/08)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING

import pytest

from spidey.platform.events import (
    EventEnvelope,
    EventPersister,
    LlmCallCompleted,
    OutboxRelay,
    OutboxWriter,
    RunEventReader,
    stream_key_for,
)
from spidey.platform.events.contracts import MessageReceived
from tests.conftest import app_container, bootstrap_admin

if TYPE_CHECKING:
    import httpx

pytestmark = pytest.mark.integration


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _llm_event(run_id: uuid.UUID) -> EventEnvelope:
    return EventEnvelope.of(
        LlmCallCompleted(
            provider="anthropic",
            model="claude-sonnet-5",
            role="planner",
            prompt_tokens=100,
            completion_tokens=20,
            latency_ms=350,
            cost_usd=0.002,
        ),
        run_id=run_id,
        actor="tester",
    )


class TestOutboxToDurableLog:
    async def test_outbox_relays_persists_and_reads_back(
        self, app_client: httpx.AsyncClient
    ) -> None:
        container = app_container(app_client)
        run_id = uuid.uuid4()
        envelope = _llm_event(run_id)

        # Producer: stage the event in a unit of work and commit it.
        async with container.session_factory() as session:
            OutboxWriter(session).add(envelope)
            await session.commit()

        # Relay drains the outbox to Redis (firehose + per-run stream).
        relayed = await OutboxRelay(container.session_factory, container.stream_bus).drain()
        assert relayed >= 1

        # Persister projects the firehose into the durable log.
        persisted = await EventPersister(container.stream_bus, container.session_factory).pump(
            consumer=f"test-{uuid.uuid4().hex[:8]}"
        )
        assert persisted >= 1

        # Timeline read returns our event with its payload intact.
        async with container.session_factory() as session:
            timeline = await RunEventReader(session).timeline(run_id)
        assert [e.event_id for e in timeline] == [envelope.event_id]
        payload = timeline[0].validated_payload()
        assert isinstance(payload, LlmCallCompleted)
        assert payload.model == "claude-sonnet-5"

    async def test_relay_is_idempotent_on_second_drain(self, app_client: httpx.AsyncClient) -> None:
        container = app_container(app_client)
        run_id = uuid.uuid4()
        async with container.session_factory() as session:
            OutboxWriter(session).add(_llm_event(run_id))
            await session.commit()

        first = await OutboxRelay(container.session_factory, container.stream_bus).drain()
        second = await OutboxRelay(container.session_factory, container.stream_bus).drain()
        assert first >= 1
        # The relayed row is marked, so a second drain does not re-relay it.
        assert second == 0


class TestSseStreaming:
    async def test_stream_requires_run_ownership(self, app_client: httpx.AsyncClient) -> None:
        token = await bootstrap_admin(app_client)
        # No owner recorded for this run → not found.
        response = await app_client.get(f"/api/v1/runs/{uuid.uuid4()}/events", headers=_auth(token))
        assert response.status_code == 404

    async def test_owner_streams_events(self, app_client: httpx.AsyncClient) -> None:
        from spidey.api.v1.runs import set_run_owner

        token = await bootstrap_admin(app_client)
        container = app_container(app_client)
        # Resolve the owning user id from the token's account.
        me = await app_client.get("/api/v1/users/me", headers=_auth(token))
        owner_id = uuid.UUID(me.json()["id"])
        run_id = uuid.uuid4()
        await set_run_owner(container.redis, run_id, owner_id)

        # Publish a frame directly to the per-run stream (as the worker would).
        frame = EventEnvelope.of(
            MessageReceived(role="assistant", content_preview="hello"), run_id=run_id
        )
        await container.stream_bus.publish(
            stream_key_for(run_id), json.dumps(frame.model_dump(mode="json"))
        )

        received: list[dict[str, object]] = []
        async with app_client.stream(
            "GET", f"/api/v1/runs/{run_id}/events", headers=_auth(token)
        ) as response:
            assert response.status_code == 200

            async def _read() -> None:
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        received.append(json.loads(line[len("data:") :].strip()))
                        return

            await asyncio.wait_for(_read(), timeout=10)

        assert received
        assert received[0]["event_type"] == "chat.message_received"
