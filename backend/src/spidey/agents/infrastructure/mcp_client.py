"""SDK-backed :class:`McpSession` — thin glue over an initialized MCP client.

The connection/handshake lifecycle (stdio child process or streamable-HTTP,
scrubbed env, ``initialize``) is owned by the composition root; this wraps the
resulting session so the tested :class:`McpProvider` (pinning, drift, sanitize)
sees the same port whether the server is real or faked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.agents.domain.mcp import McpCallResult, McpToolDef

if TYPE_CHECKING:
    from mcp import ClientSession


class SdkMcpSession:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def list_tools(self) -> list[McpToolDef]:
        result = await self._session.list_tools()
        return [
            McpToolDef(
                name=tool.name,
                description=tool.description or "",
                input_schema=dict(tool.inputSchema),
            )
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, object]) -> McpCallResult:
        result = await self._session.call_tool(name, arguments)
        text = "\n".join(
            getattr(block, "text", "")
            for block in result.content
            if getattr(block, "type", None) == "text"
        )
        return McpCallResult(content=text, is_error=bool(result.isError))
