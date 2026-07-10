"""Celery application factory and worker-process bootstrap.

Contract: tasks are acknowledged late and never run unbounded — every task has
a soft/hard time limit. Logging goes through the platform structlog pipeline
(Celery's own logging setup is disabled), and OTel instrumentation propagates
trace context from enqueuing code into task spans (docs/09 §2).
"""

from __future__ import annotations

from typing import Any

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging
from celery.signals import worker_process_init

from spidey.platform.config import Settings, get_settings
from spidey.platform.logging import configure_logging
from spidey.platform.telemetry import instrument_celery, setup_tracing

TASK_MODULES = (
    "spidey.workers.tasks.maintenance",
    "spidey.workers.tasks.ingestion",
)

HEARTBEAT_INTERVAL_SECONDS = 60.0


def create_celery_app(settings: Settings | None = None) -> Celery:
    settings = settings if settings is not None else get_settings()
    celery_app = Celery("spidey", broker=settings.redis_dsn, backend=settings.redis_dsn)
    celery_app.conf.update(
        include=list(TASK_MODULES),
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_soft_time_limit=300,
        task_time_limit=360,
        result_expires=3600,
        broker_connection_retry_on_startup=True,
        worker_hijack_root_logger=False,
        task_default_queue="maintenance",
        task_routes={"spidey.workspaces.ingest": {"queue": "ingestion"}},
        beat_schedule={
            "platform-heartbeat": {
                "task": "spidey.maintenance.heartbeat",
                "schedule": HEARTBEAT_INTERVAL_SECONDS,
            },
        },
    )
    return celery_app


@celery_setup_logging.connect
def configure_worker_logging(**_: Any) -> None:
    """Route Celery logging through the platform pipeline instead of its own."""
    configure_logging(get_settings())


@worker_process_init.connect
def configure_worker_telemetry(**_: Any) -> None:
    """Per-worker-process tracing: provider + Celery task span instrumentation."""
    setup_tracing(get_settings())
    instrument_celery()


app = create_celery_app()
