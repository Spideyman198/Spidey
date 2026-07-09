"""Secret and PII redaction for logs, telemetry, and captured payloads.

Contract: redaction is applied at the *choke points* (log pipeline now; memory
write gate and replay capture when those land) so sensitive values never reach
disk. Patterns favor recall over precision — a redacted benign value costs a
little debuggability; a leaked credential costs an incident. This module is
pure (no I/O) and safe to call from any layer.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from structlog.typing import EventDict, WrappedLogger

REDACTED = "[REDACTED]"
_MAX_DEPTH = 8

# Keys whose values are secret by definition, wherever they appear.
_SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|token|api[-_]?key|authorization|auth[-_]?header"
    r"|credential|cookie|session[-_]?id|private[-_]?key|client[-_]?secret)"
)

# Value shapes that are secrets regardless of the key they hide under.
_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]{8,}"),  # Authorization: Bearer …
    re.compile(r"\bsk-ant-[a-zA-Z0-9_-]{8,}\b"),  # Anthropic
    re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b"),  # OpenAI-style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),  # GitHub classic tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),  # GitHub fine-grained
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),  # Slack
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)

# Credentials embedded in URLs: scheme://user:password@host → mask the password.
_URL_CREDENTIALS = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@/\s]+)(@)")

# PII: email local parts are masked, domain kept (useful for debugging, low risk).
_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")


def scrub_text(value: str) -> str:
    """Redact secret-shaped substrings and mask PII inside a string."""
    for pattern in _VALUE_PATTERNS:
        value = pattern.sub(REDACTED, value)
    value = _URL_CREDENTIALS.sub(rf"\1{REDACTED}\3", value)
    return _EMAIL.sub(r"\1***\2", value)


def _scrub(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return REDACTED  # refuse to inspect unboundedly nested payloads
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if isinstance(key, str) and _SENSITIVE_KEY.search(key)
                else _scrub(item, depth + 1)
            )
            for key, item in value.items()  # pyright: ignore[reportUnknownVariableType]
        }
    if isinstance(value, (list, tuple)):
        items = [_scrub(item, depth + 1) for item in value]  # pyright: ignore[reportUnknownVariableType]
        return items if isinstance(value, list) else tuple(items)
    return value


def scrub_event_dict(
    logger: WrappedLogger,  # noqa: ARG001 — structlog processor signature
    method_name: str,  # noqa: ARG001
    event_dict: EventDict,
) -> EventDict:
    """structlog processor: redact every value in the event before rendering."""
    return {
        key: (REDACTED if _SENSITIVE_KEY.search(key) else _scrub(value, 0))
        for key, value in event_dict.items()
    }
