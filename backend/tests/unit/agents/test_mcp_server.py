"""Spidey-as-MCP-server: registry → MCP tools/list + tools/call mapping."""

from __future__ import annotations

import uuid

from spidey.agents.application import ToolRegistry
from spidey.agents.domain import (
    SideEffect,
    ToolContext,
    ToolResult,
    ToolSpec,
    TrustTier,
)
from spidey.agents.infrastructure import SpideyMcpTools
from spidey.identity.domain.models import Role


class Provider:
    @property
    def namespace(self) -> str:
        return "demo"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="demo.read",
                description="a read tool",
                input_schema={"type": "object"},
                side_effect=SideEffect.READ,
                trust_tier=TrustTier.TRUSTED,
                required_role=Role.VIEWER,
            ),
        ]

    async def invoke(
        self, name: str, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        return ToolResult.success("read result")


def _context() -> ToolContext:
    return ToolContext(actor_user_id=uuid.uuid4(), role=Role.DEVELOPER)


def test_list_tools_maps_annotations() -> None:
    tools = SpideyMcpTools(ToolRegistry(providers=[Provider()]))
    listed = tools.list_tools(_context())
    assert [t.name for t in listed] == ["demo.read"]
    assert listed[0].annotations is not None
    assert listed[0].annotations.readOnlyHint is True
    assert listed[0].annotations.destructiveHint is False


async def test_call_tool_wraps_result() -> None:
    tools = SpideyMcpTools(ToolRegistry(providers=[Provider()]))
    result = await tools.call_tool("demo.read", {}, _context())
    assert result.isError is False
    assert result.content[0].type == "text"
    assert "read result" in result.content[0].text  # type: ignore[union-attr]


async def test_call_unknown_tool_is_error() -> None:
    tools = SpideyMcpTools(ToolRegistry(providers=[Provider()]))
    result = await tools.call_tool("demo.nope", {}, _context())
    assert result.isError is True
