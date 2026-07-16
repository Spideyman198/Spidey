"""LLM gateway error taxonomy.

Adapters translate provider failures into two shapes the gateway understands:
:class:`TransientProviderError` (retry, then fall back) and
:class:`ProviderError` (don't retry; fall back). Budget denial and total
exhaustion surface as their own types.
"""

from __future__ import annotations

from typing import ClassVar

from spidey.platform.errors import ErrorCode, SpideyError


class ProviderError(SpideyError):
    """A provider call failed in a way retrying won't fix (auth, bad request)."""

    code: ClassVar[ErrorCode] = ErrorCode.SERVICE_UNAVAILABLE
    status: ClassVar[int] = 502
    title: ClassVar[str] = "LLM provider error"


class TransientProviderError(ProviderError):
    """A transient provider failure (429, 5xx, timeout) — safe to retry."""


class AllProvidersFailedError(ProviderError):
    """Every model in the role's fallback chain failed."""

    title: ClassVar[str] = "All LLM providers failed"


class BudgetExceededError(SpideyError):
    """The call would exceed the scope's token/cost budget (NFR-5)."""

    code: ClassVar[ErrorCode] = ErrorCode.RATE_LIMITED
    status: ClassVar[int] = 429
    title: ClassVar[str] = "LLM budget exceeded"
