"""Serve the ToolRegistry over MCP (docs/05 §3).

Spidey is itself an MCP server: the same tools, the same choke point. Every
list/call routes through :class:`ToolRegistry`, so MCP callers get identical
RBAC, gating, sanitization, and audit as REST — MCP is a transport, not a
principal. Side-effect classes map to MCP annotations (``readOnlyHint`` /
``destructiveHint``); a ``destructive`` call still returns a gated result until
the approval flow (M7).

The registry-to-MCP mapping lives in :class:`SpideyMcpTools` (directly testable);
``build_spidey_mcp_server`` binds it to the SDK server for a transport to mount.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp import types as mcp_types
from mcp.server.lowlevel import Server

from spidey.agents.domain.tools import SideEffect

if TYPE_CHECKING:
    from collections.abc import Callable

    from spidey.agents.application.registry import ToolRegistry
    from spidey.agents.domain.tools import ToolContext


class SpideyMcpTools:
    """Maps the registry to MCP ``tools/list`` and ``tools/call`` results."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def list_tools(self, context: ToolContext) -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=dict(spec.input_schema),
                annotations=mcp_types.ToolAnnotations(
                    readOnlyHint=spec.side_effect is SideEffect.READ,
                    destructiveHint=spec.side_effect is SideEffect.DESTRUCTIVE,
                ),
            )
            for spec in self._registry.list_tools(context.role)
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, object], context: ToolContext
    ) -> mcp_types.CallToolResult:
        result = await self._registry.invoke(name=name, arguments=arguments, context=context)
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=result.content)],
            isError=not result.ok,
        )


def build_spidey_mcp_server(
    registry: ToolRegistry, *, context_provider: Callable[[], ToolContext]
) -> Server:
    """Bind the registry to an SDK server. ``context_provider`` resolves the
    authenticated caller (bearer token → identity) for the current request, so
    RBAC is enforced with the same principal as REST."""
    server: Server = Server("spidey")
    tools = SpideyMcpTools(registry)

    @server.list_tools()
    async def _list() -> list[mcp_types.Tool]:  # pyright: ignore[reportUnusedFunction]
        return tools.list_tools(context_provider())

    @server.call_tool()
    async def _call(  # pyright: ignore[reportUnusedFunction]
        name: str, arguments: dict[str, object]
    ) -> mcp_types.CallToolResult:
        return await tools.call_tool(name, arguments, context_provider())

    return server
