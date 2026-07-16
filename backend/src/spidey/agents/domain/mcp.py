"""External-MCP domain types (docs/05 §4).

Consuming an external MCP server is the extension mechanism — and the biggest
trust boundary. These types carry what the registry needs to mount one safely:
a session port (so the SDK transport is an adapter, not a dependency of the
security logic), a reviewed per-server config, and a content hash used to pin
the tool set against silent rug-pulls.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

from spidey.agents.domain.tools import TrustTier
from spidey.identity.domain.models import Role

if TYPE_CHECKING:
    from collections.abc import Sequence


class McpToolDef(BaseModel):
    """A tool as advertised by an MCP server's ``tools/list``."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    input_schema: dict[str, object] = Field(default_factory=lambda: {"type": "object"})


class McpCallResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = ""
    is_error: bool = False


class McpServerConfig(BaseModel):
    """Reviewed, static config for one mounted server (``mcp_servers.yaml``)."""

    model_config = ConfigDict(frozen=True)

    namespace: str
    trust_tier: TrustTier = TrustTier.UNTRUSTED
    # Pinned tool-set hash. None on first mount (operator pins it after review);
    # a mismatch later is a rug-pull and disables the server (drift alarm).
    pinned_hash: str | None = None
    # Allow-list of tool names to expose; None means all advertised tools.
    allowed_tools: frozenset[str] | None = None
    required_role: Role = Role.DEVELOPER


class McpSession(Protocol):
    """The minimal client surface the provider needs — implemented by an SDK
    transport adapter (stdio / streamable HTTP), faked in tests."""

    async def list_tools(self) -> list[McpToolDef]: ...

    async def call_tool(self, name: str, arguments: dict[str, object]) -> McpCallResult: ...


def compute_tool_hash(defs: Sequence[McpToolDef]) -> str:
    """Stable hash of a server's tool set — name + schema + description.

    Pinned at first mount; a later change to any description or schema (the
    documented tool-poisoning / rug-pull vector) changes this hash."""
    canonical = json.dumps(
        [
            {"name": d.name, "description": d.description, "input_schema": d.input_schema}
            for d in sorted(defs, key=lambda d: d.name)
        ],
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
