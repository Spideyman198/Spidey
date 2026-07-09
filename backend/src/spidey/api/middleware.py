"""ASGI middleware: request context, security headers, Prometheus metrics."""

from __future__ import annotations

import re
import time
import uuid
from typing import TYPE_CHECKING

import structlog
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware

from spidey.api.errors import unexpected_error_response
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

    RequestHandler = Callable[[Request], Awaitable[Response]]

_logger = get_logger("spidey.api.request")

# Accept caller-supplied request ids only when they are log-safe.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

HTTP_REQUESTS = Counter(
    "spidey_http_requests_total",
    "HTTP requests processed",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "spidey_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id into log context; echo it back; log one line per request."""

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _SAFE_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex

        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            _logger.exception(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

        response.headers["X-Request-ID"] = request_id
        _logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers for an API-only origin (docs 11, layer 1).

    Also the innermost catch for unexpected exceptions: Starlette's bare
    ``Exception`` handler runs *outside* the middleware stack, so converting
    here keeps security headers and metrics correct on 500 responses.
    """

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        try:
            response = await call_next(request)
        except Exception as exc:
            response = unexpected_error_response(request, exc)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        # The API serves no HTML except the docs UI; lock everything else down.
        if not request.url.path.endswith("/docs"):
            headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        headers.setdefault("Cache-Control", "no-store")
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """RED metrics per route template (never per raw path — bounded cardinality)."""

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            HTTP_REQUESTS.labels(request.method, _route_template(request), "500").inc()
            raise
        route = _route_template(request)
        HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, route).observe(time.perf_counter() - started)
        return response
