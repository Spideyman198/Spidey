"""Maintenance-queue tasks."""

from __future__ import annotations

from datetime import UTC, datetime

from celery import shared_task

from spidey.platform.logging import get_logger

_logger = get_logger("spidey.workers.maintenance")


@shared_task(name="spidey.maintenance.heartbeat")
def heartbeat() -> str:
    """Liveness signal for the worker plane.

    Scheduled by beat every minute; the returned timestamp lands in the result
    backend, and the log line (with trace id via instrumentation) proves the
    broker → worker → backend path end to end.
    """
    now = datetime.now(tz=UTC).isoformat()
    _logger.info("worker_heartbeat", at=now)
    return now
