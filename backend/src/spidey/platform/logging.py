"""Structured logging: structlog pipeline with stdlib bridging.

Contract: every log line is a structured event carrying ``trace_id``/``span_id``
(when a span is active) and any bound context (``request_id`` etc.), passed
through secret/PII redaction before rendering. Third-party stdlib loggers
(uvicorn, celery, alembic) render through the same pipeline, so operators see
one consistent stream. Output: pretty console in dev, JSON everywhere else.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from spidey.platform.config import Environment, Settings
from spidey.platform.security.scrubbing import scrub_event_dict

if TYPE_CHECKING:
    from structlog.typing import EventDict, Processor, WrappedLogger


def add_trace_context(
    logger: WrappedLogger,  # noqa: ARG001 — structlog processor signature
    method_name: str,  # noqa: ARG001
    event_dict: EventDict,
) -> EventDict:
    """Attach the active OTel trace/span ids so logs and traces cross-link."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = format(span_context.trace_id, "032x")
        event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_trace_context,
        scrub_event_dict,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the stdlib root logger. Idempotent."""
    shared = _shared_processors()
    renderer: Processor = (
        structlog.dev.ConsoleRenderer(colors=True)
        if settings.environment is Environment.DEV
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.value)

    # Uvicorn's access log duplicates our request middleware logging; keep its
    # error channel, drop the access noise.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Project-standard logger accessor; use instead of importing structlog."""
    return structlog.stdlib.get_logger(name)
