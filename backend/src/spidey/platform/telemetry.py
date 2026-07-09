"""OpenTelemetry bootstrap.

Contract: telemetry is always *on* in-process (spans exist, ids flow into
logs) and degrades to a no-op export when no collector endpoint is configured —
the application never fails because observability infrastructure is absent.
Export protocol is OTLP over HTTP/protobuf (collector port 4318), chosen over
gRPC to avoid the grpcio build/runtime weight for identical functionality here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

import spidey

if TYPE_CHECKING:
    from fastapi import FastAPI

    from spidey.platform.config import Settings

_configured = False


def setup_tracing(settings: Settings) -> None:
    """Install the global tracer provider. Idempotent across app factories."""
    global _configured  # noqa: PLW0603 — process-wide OTel state is inherently global
    if _configured:
        return

    resource = Resource.create(
        {
            SERVICE_NAME: settings.otel_service_name,
            SERVICE_VERSION: spidey.__version__,
            "deployment.environment": settings.environment.value,
        }
    )
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_otlp_endpoint is not None:
        endpoint = str(settings.otel_exporter_otlp_endpoint).rstrip("/") + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))

    trace.set_tracer_provider(provider)
    _configured = True


def instrument_fastapi(app: FastAPI) -> None:
    """Attach OTel ASGI instrumentation (server spans per request)."""
    FastAPIInstrumentor.instrument_app(app, exclude_spans=["receive", "send"])


def instrument_celery() -> None:
    """Attach OTel Celery instrumentation (task spans, context propagation)."""
    CeleryInstrumentor().instrument()
