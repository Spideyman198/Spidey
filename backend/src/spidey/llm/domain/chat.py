"""Provider-neutral chat domain types (ADR-0009).

These are the seam every caller and every provider adapter speak. Tool-calling,
streaming, and usage are first-class here so the gateway can meter, budget, and
replay uniformly — the per-provider dialect differences are normalized inside
the adapters, never leaked to callers.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    """Agent role → routed to a (provider, model) by config (ADR-0012)."""

    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    SUMMARIZER = "summarizer"
    CHAT = "chat"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(StrEnum):
    STOP = "stop"
    TOOL_USE = "tool_use"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"


class ToolSchema(BaseModel):
    """A tool offered to the model — MCP-compatible JSON Schema (docs/05)."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, object]


class ToolCall(BaseModel):
    """The model's request to invoke a tool."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, object]


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: MessageRole
    content: str = ""
    # Assistant messages may request tools; tool messages carry a result.
    tool_calls: list[ToolCall] = Field(default_factory=list[ToolCall])
    tool_call_id: str | None = None
    name: str | None = None

    @classmethod
    def system(cls, content: str) -> ChatMessage:
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> ChatMessage:
        return cls(role=MessageRole.USER, content=content)

    @classmethod
    def tool_result(cls, *, tool_call_id: str, name: str, content: str) -> ChatMessage:
        return cls(role=MessageRole.TOOL, tool_call_id=tool_call_id, name=name, content=content)


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ChatRequest(BaseModel):
    """A provider-neutral completion request. The gateway resolves the role to a
    concrete model before handing this to an adapter."""

    model_config = ConfigDict(frozen=True)

    messages: list[ChatMessage]
    tools: list[ToolSchema] = Field(default_factory=list[ToolSchema])
    max_tokens: int = 1024
    temperature: float = 0.0


class ChatResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    message: ChatMessage
    finish_reason: FinishReason
    usage: Usage
    provider: str
    model: str

    @property
    def text(self) -> str:
        return self.message.content


class ChatChunk(BaseModel):
    """One streaming delta. A run of ``text_delta``s, then optional ``tool_call``s,
    then a final chunk carrying ``usage`` + ``finish_reason``."""

    model_config = ConfigDict(frozen=True)

    text_delta: str = ""
    tool_call: ToolCall | None = None
    usage: Usage | None = None
    finish_reason: FinishReason | None = None
