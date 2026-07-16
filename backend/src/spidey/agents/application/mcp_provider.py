"""Mounting external MCP servers safely (docs/05 §4).

The provider is a :class:`ToolProvider` backed by an :class:`McpSession`. At mount
it hashes the advertised tool set and compares to the reviewed pin: a mismatch is
a rug-pull, so the server is **disabled** and a drift alarm fires (no tools are
exposed until the new hash is re-approved). Descriptions from untrusted servers
are injection-screened before they can ever reach a prompt (tool-poisoning
defense). Tool *output* is sanitized downstream by the registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from prometheus_client import Counter

from spidey.agents.domain.mcp import compute_tool_hash
from spidey.agents.domain.tools import SideEffect, ToolResult, ToolSpec, TrustTier
from spidey.platform.logging import get_logger
from spidey.platform.security import looks_like_injection

if TYPE_CHECKING:
    from spidey.agents.domain.mcp import McpServerConfig, McpSession, McpToolDef
    from spidey.agents.domain.tools import ToolContext

_logger = get_logger("spidey.agents.mcp")
_MAX_DESCRIPTION = 2_000
_DRIFT_ALARMS = Counter(
    "spidey_mcp_drift_alarms",
    "MCP tool-definition drift alarms (a mounted server's tool set changed).",
    ["server"],
)


class McpProvider:
    """A mounted external server, exposed through the registry like any provider."""

    def __init__(
        self,
        *,
        session: McpSession,
        config: McpServerConfig,
        specs: list[ToolSpec],
        tool_map: dict[str, str],
        disabled: bool = False,
    ) -> None:
        self._session = session
        self._config = config
        self._specs = specs
        self._tool_map = tool_map
        self._disabled = disabled

    @property
    def namespace(self) -> str:
        return self._config.namespace

    def specs(self) -> list[ToolSpec]:
        return [] if self._disabled else self._specs

    async def invoke(
        self,
        name: str,
        arguments: dict[str, object],
        context: ToolContext,  # noqa: ARG002
    ) -> ToolResult:
        if self._disabled:
            return ToolResult.unavailable("server disabled pending drift re-approval")
        mcp_name = self._tool_map.get(name)
        if mcp_name is None:
            return ToolResult.error(f"unknown tool {name!r}")
        try:
            result = await self._session.call_tool(mcp_name, arguments)
        except Exception:
            _logger.exception("mcp_call_failed", server=self._config.namespace, tool=name)
            return ToolResult.unavailable("mcp server call failed")
        if result.is_error:
            return ToolResult.error(result.content)
        return ToolResult.success(result.content)


@dataclass(frozen=True, slots=True)
class MountOutcome:
    provider: McpProvider
    drift: bool
    tool_hash: str


async def mount_mcp_server(*, session: McpSession, config: McpServerConfig) -> MountOutcome:
    """Handshake, hash, pin-check, and build a provider (disabled on drift)."""
    defs = await session.list_tools()
    tool_hash = compute_tool_hash(defs)
    if config.pinned_hash is not None and tool_hash != config.pinned_hash:
        _DRIFT_ALARMS.labels(config.namespace).inc()
        _logger.warning(
            "mcp_tool_drift",
            server=config.namespace,
            expected=config.pinned_hash,
            actual=tool_hash,
        )
        disabled = McpProvider(session=session, config=config, specs=[], tool_map={}, disabled=True)
        return MountOutcome(provider=disabled, drift=True, tool_hash=tool_hash)

    specs, tool_map = _build_specs(defs, config)
    provider = McpProvider(session=session, config=config, specs=specs, tool_map=tool_map)
    return MountOutcome(provider=provider, drift=False, tool_hash=tool_hash)


def _build_specs(
    defs: list[McpToolDef], config: McpServerConfig
) -> tuple[list[ToolSpec], dict[str, str]]:
    specs: list[ToolSpec] = []
    tool_map: dict[str, str] = {}
    for definition in defs:
        if config.allowed_tools is not None and definition.name not in config.allowed_tools:
            continue
        full_name = f"{config.namespace}.{definition.name}"
        specs.append(
            ToolSpec(
                name=full_name,
                description=_safe_description(definition.description, config.trust_tier),
                input_schema=definition.input_schema,
                side_effect=SideEffect.READ,  # M6 mounts read-only servers only
                trust_tier=config.trust_tier,
                required_role=config.required_role,
            )
        )
        tool_map[full_name] = definition.name
    return specs, tool_map


def _safe_description(description: str, tier: TrustTier) -> str:
    capped = description[:_MAX_DESCRIPTION]
    if tier is TrustTier.UNTRUSTED and looks_like_injection(capped):
        return "(description withheld: failed injection screen)"
    return capped
