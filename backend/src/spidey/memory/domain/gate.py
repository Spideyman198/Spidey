"""Memory write gate (M11, docs/07 §3) — the one door long-term memory writes go
through.

A memory is a *fact*, never an instruction. If agents (or repo content that
reached an agent) could persist imperatives into memory, memory would become a
prompt-injection persistence mechanism that survives across sessions. So every
candidate is screened before storage:

1. **schema/size** — non-empty, bounded content;
2. **injection / imperative scan** — reject anything that reads as a command;
3. **PII + secret scrub** — redact before storage, never after recall;
4. **scope validation** — a cross-repo ``semantic`` memory may carry no workspace
   scope; workspace-scoped kinds must name their workspace;
5. **dedupe** — a candidate identical to an existing memory is dropped.

Pure and side-effect-free, so the whole decision surface is unit-testable.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from spidey.memory.domain.longterm import (
    WORKSPACE_SCOPED_KINDS,
    MemoryCandidate,
    MemoryKind,
)
from spidey.platform.security import looks_like_injection, scrub_text

_MAX_CONTENT_CHARS = 2000
_MIN_CONTENT_CHARS = 3

# Imperative / directive shapes: a memory must read as an observation, not a
# command. These catch the residue an injection scan might miss (plain commands).
_IMPERATIVE = re.compile(
    r"(?i)(?:^|[.\n]\s*)(ignore|disregard|override|run|execute|delete|remove|drop|"
    r"install|download|curl|wget|always|never|you must|you should|do not|don'?t|"
    r"please\s+\w+|send|email|exfiltrate)\b"
)


class GateOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class GateDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: GateOutcome
    reason: str = ""
    content: str = ""  # scrubbed, storage-ready content when accepted

    @property
    def accepted(self) -> bool:
        return self.outcome is GateOutcome.ACCEPTED


def _reject(reason: str) -> GateDecision:
    return GateDecision(outcome=GateOutcome.REJECTED, reason=reason)


def evaluate(candidate: MemoryCandidate, *, existing_contents: set[str]) -> GateDecision:
    """Screen one candidate. Returns an ACCEPTED decision carrying the scrubbed
    content, or a REJECTED decision with a safe reason (never the raw value)."""
    raw = candidate.content.strip()
    if len(raw) < _MIN_CONTENT_CHARS:
        return _reject("content too short")
    if len(raw) > _MAX_CONTENT_CHARS:
        return _reject("content too long")

    # A memory is a fact, not an instruction (the core invariant).
    if looks_like_injection(raw) or _IMPERATIVE.search(raw):
        return _reject("content reads as an instruction, not a fact")

    scope_reason = _scope_reason(candidate)
    if scope_reason is not None:
        return _reject(scope_reason)

    # PII/secret scrub happens *before* storage, so a leaked value never lands.
    scrubbed = scrub_text(raw)

    if _normalize(scrubbed) in {_normalize(c) for c in existing_contents}:
        return _reject("duplicate of an existing memory")

    return GateDecision(outcome=GateOutcome.ACCEPTED, content=scrubbed)


def _scope_reason(candidate: MemoryCandidate) -> str | None:
    """Scope rules (docs/07 §4): semantic is the only cross-repo kind and must not
    be workspace-scoped; workspace-scoped kinds must name their workspace."""
    if candidate.kind is MemoryKind.SEMANTIC and candidate.scope.workspace_id is not None:
        return "semantic memory must not carry a workspace scope"
    if candidate.kind in WORKSPACE_SCOPED_KINDS and candidate.scope.workspace_id is None:
        return f"{candidate.kind.value} memory requires a workspace scope"
    return None


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())
