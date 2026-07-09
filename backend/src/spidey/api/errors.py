"""Exception → RFC 9457 problem-details translation for the HTTP layer.

Contract: clients always receive ``application/problem+json`` with a stable
``type`` URN they can program against. Unexpected exceptions never leak
internals — detail is generic, the trace id is the debugging handle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi.exceptions import RequestValidationError
from opentelemetry import trace
from starlette.responses import JSONResponse

from spidey.platform.errors import ErrorCode, SpideyError
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request

_logger = get_logger("spidey.api.errors")

PROBLEM_CONTENT_TYPE = "application/problem+json"


def _current_trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    return format(span_context.trace_id, "032x") if span_context.is_valid else None


def _problem_response(problem: dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        content=problem,
        status_code=int(problem["status"]),
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def _handle_spidey_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, SpideyError)  # noqa: S101 — registered for this type
    _logger.warning("domain_error", code=exc.code.value, detail=exc.detail, **exc.context)
    return _problem_response(
        exc.to_problem(instance=request.url.path, trace_id=_current_trace_id())
    )


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    problem: dict[str, Any] = {
        "type": f"urn:spidey:error:{ErrorCode.VALIDATION.value}",
        "title": "Validation failed",
        "status": 422,
        "detail": "Request did not match the expected schema.",
        "instance": request.url.path,
        "errors": [
            {"loc": list(err.get("loc", ())), "msg": str(err.get("msg", ""))}
            for err in exc.errors()
        ],
    }
    if (trace_id := _current_trace_id()) is not None:
        problem["trace_id"] = trace_id
    return _problem_response(problem)


def unexpected_error_response(request: Request, exc: Exception) -> JSONResponse:
    """Generic 500 problem. Shared by the middleware catch (keeps security
    headers on error responses) and the last-resort exception handler."""
    _logger.exception("unhandled_error", path=request.url.path, error_type=type(exc).__name__)
    problem: dict[str, Any] = {
        "type": f"urn:spidey:error:{ErrorCode.INTERNAL.value}",
        "title": "Internal error",
        "status": 500,
        "detail": "An unexpected error occurred. Reference the trace id when reporting.",
        "instance": request.url.path,
    }
    if (trace_id := _current_trace_id()) is not None:
        problem["trace_id"] = trace_id
    return _problem_response(problem)


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    return unexpected_error_response(request, exc)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(SpideyError, _handle_spidey_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected)
