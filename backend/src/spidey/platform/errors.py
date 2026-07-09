"""Error taxonomy and RFC 9457 problem-details mapping.

Contract: domain and application code raises :class:`SpideyError` subclasses;
only the interface layer translates them to transport responses. Problem
responses never contain stack traces, internal identifiers beyond the trace id,
or secrets — regardless of environment.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, ClassVar


class ErrorCode(StrEnum):
    INTERNAL = "internal-error"
    VALIDATION = "validation-error"
    NOT_FOUND = "not-found"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate-limited"
    SERVICE_UNAVAILABLE = "service-unavailable"


class SpideyError(Exception):
    """Base class for all first-party errors.

    ``detail`` is safe for clients by contract: callers must not embed secrets
    or internals in it. ``context`` is for logs only and is never serialized
    into a response.
    """

    code: ClassVar[ErrorCode] = ErrorCode.INTERNAL
    status: ClassVar[int] = 500
    title: ClassVar[str] = "Internal error"

    def __init__(self, detail: str, **context: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.context: dict[str, Any] = context

    def to_problem(
        self, *, instance: str | None = None, trace_id: str | None = None
    ) -> dict[str, Any]:
        """Render as an RFC 9457 problem-details object."""
        problem: dict[str, Any] = {
            "type": f"urn:spidey:error:{self.code.value}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
        }
        if instance is not None:
            problem["instance"] = instance
        if trace_id is not None:
            problem["trace_id"] = trace_id
        return problem


class NotFoundError(SpideyError):
    code = ErrorCode.NOT_FOUND
    status = 404
    title = "Resource not found"


class UnauthorizedError(SpideyError):
    code = ErrorCode.UNAUTHORIZED
    status = 401
    title = "Authentication required"


class ForbiddenError(SpideyError):
    code = ErrorCode.FORBIDDEN
    status = 403
    title = "Not permitted"


class ConflictError(SpideyError):
    code = ErrorCode.CONFLICT
    status = 409
    title = "Conflict"


class RateLimitedError(SpideyError):
    code = ErrorCode.RATE_LIMITED
    status = 429
    title = "Rate limit exceeded"


class ServiceUnavailableError(SpideyError):
    code = ErrorCode.SERVICE_UNAVAILABLE
    status = 503
    title = "Service unavailable"


class ValidationFailedError(SpideyError):
    code = ErrorCode.VALIDATION
    status = 422
    title = "Validation failed"
