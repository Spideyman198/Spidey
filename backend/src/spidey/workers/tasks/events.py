"""Event-plane pump (queue: maintenance, beat-scheduled).

One cycle: relay committed outbox rows to Redis Streams, then advance each
consumer group by a batch (persister → run_events, metrics → Prometheus). Driven
by beat so there is no long-lived loop; each cycle is idempotent and restart-safe.
"""

from __future__ import annotations

import asyncio

from celery import shared_task

from spidey.platform.events import EventPersister, MetricsProjector, OutboxRelay
from spidey.platform.logging import get_logger
from spidey.workers.container import get_worker_container

_logger = get_logger("spidey.workers.events")


@shared_task(name="spidey.events.pump", max_retries=0)
def pump_events() -> None:
    asyncio.run(_pump())


async def _pump() -> None:
    container = get_worker_container()
    bus = container.stream_bus
    relayed = await OutboxRelay(container.session_factory, bus).drain()
    persisted = await EventPersister(bus, container.session_factory).pump()
    projected = await MetricsProjector(bus).pump()
    if relayed or persisted or projected:
        _logger.info("event_pump", relayed=relayed, persisted=persisted, projected=projected)
