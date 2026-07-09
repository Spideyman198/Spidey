"""Error taxonomy: stable codes, RFC 9457 rendering, log-only context."""

from __future__ import annotations

from spidey.platform.errors import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
    SpideyError,
    UnauthorizedError,
)


class TestProblemRendering:
    def test_full_problem_shape(self) -> None:
        error = NotFoundError("session does not exist", session_id="abc")
        problem = error.to_problem(instance="/api/v1/sessions/abc", trace_id="0" * 32)
        assert problem == {
            "type": "urn:spidey:error:not-found",
            "title": "Resource not found",
            "status": 404,
            "detail": "session does not exist",
            "instance": "/api/v1/sessions/abc",
            "trace_id": "0" * 32,
        }

    def test_optional_fields_omitted(self) -> None:
        problem = ConflictError("duplicate").to_problem()
        assert "instance" not in problem
        assert "trace_id" not in problem

    def test_context_is_never_serialized(self) -> None:
        error = UnauthorizedError("bad token", token_fingerprint="secret-ish")
        assert "token_fingerprint" not in error.to_problem()
        assert error.context == {"token_fingerprint": "secret-ish"}


class TestTaxonomy:
    def test_status_codes(self) -> None:
        cases: list[tuple[type[SpideyError], int, ErrorCode]] = [
            (NotFoundError, 404, ErrorCode.NOT_FOUND),
            (UnauthorizedError, 401, ErrorCode.UNAUTHORIZED),
            (ConflictError, 409, ErrorCode.CONFLICT),
            (RateLimitedError, 429, ErrorCode.RATE_LIMITED),
            (ServiceUnavailableError, 503, ErrorCode.SERVICE_UNAVAILABLE),
        ]
        for error_class, status, code in cases:
            error = error_class("detail")
            assert error.status == status
            assert error.code is code

    def test_str_is_detail(self) -> None:
        assert str(NotFoundError("nope")) == "nope"
