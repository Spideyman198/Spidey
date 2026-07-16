"""Tool-plane domain types — MCP-shaped (docs/05, ADR-0010).

A ``ToolSpec`` carries everything the registry needs to gate an invocation:
its JSON-Schema contract, a side-effect class, a trust tier, and the minimum
role. Providers (native or MCP) contribute specs and an ``invoke``; the registry
is the one choke point where RBAC, schema validation, side-effect gating,
sanitization, budgets, events, and audit are applied — no transport bypasses it.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from spidey.identity.domain.models import Role


class SideEffect(StrEnum):
    """How dangerous an invocation is. Drives approval gating (docs/05)."""

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class TrustTier(StrEnum):
    """Provenance of a tool's implementation → how much its output is trusted."""

    TRUSTED = "trusted"  # our native, in-process code
    VERIFIED = "verified"  # a reviewed, pinned external MCP server
    UNTRUSTED = "untrusted"  # anything else — output is hostile until proven otherwise


class ToolOutcome(StrEnum):
    OK = "ok"
    ERROR = "error"
    UNAVAILABLE = "unavailable"
    DENIED = "denied"


class ToolSpec(BaseModel):
    """The contract for one tool. ``name`` is server-namespaced (``codeintel.search``)."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: int = 1
    description: str
    input_schema: dict[str, object] = Field(default_factory=lambda: {"type": "object"})
    side_effect: SideEffect = SideEffect.READ
    trust_tier: TrustTier = TrustTier.TRUSTED
    required_role: Role = Role.VIEWER
    timeout_seconds: float = 30.0
    cost_hint: str | None = None


class ToolContext(BaseModel):
    """The caller's identity + correlation, carried into every invocation."""

    model_config = ConfigDict(frozen=True)

    actor_user_id: uuid.UUID
    role: Role
    run_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    trace_id: str | None = None
    span_id: str | None = None


class ToolResult(BaseModel):
    """The typed outcome of an invocation. A tool never raises across the registry
    boundary — failure is a value the caller can plan around (docs/05 §6)."""

    model_config = ConfigDict(frozen=True)

    outcome: ToolOutcome
    content: str = ""
    # Set when the output tripped the injection screen (non-trusted providers).
    suspect: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome is ToolOutcome.OK

    @classmethod
    def success(cls, content: str, *, suspect: bool = False) -> ToolResult:
        return cls(outcome=ToolOutcome.OK, content=content, suspect=suspect)

    @classmethod
    def denied(cls, reason: str) -> ToolResult:
        return cls(outcome=ToolOutcome.DENIED, content=reason)

    @classmethod
    def unavailable(cls, reason: str) -> ToolResult:
        return cls(outcome=ToolOutcome.UNAVAILABLE, content=reason)

    @classmethod
    def error(cls, reason: str) -> ToolResult:
        return cls(outcome=ToolOutcome.ERROR, content=reason)
