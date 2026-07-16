"""Anthropic adapter — native SDK behind the :class:`ChatModel` seam (ADR-0009).

Translates our provider-neutral chat types to/from the Messages API: system
messages become the ``system`` param, tool calls and tool results become
``tool_use``/``tool_result`` blocks, and provider failures are mapped to the
gateway's transient/permanent error taxonomy so retries and fallback behave.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
)

from spidey.llm.domain.capabilities import CapabilityManifest
from spidey.llm.domain.chat import (
    ChatChunk,
    ChatMessage,
    ChatResponse,
    FinishReason,
    MessageRole,
    ToolCall,
    Usage,
)
from spidey.llm.domain.errors import ProviderError, TransientProviderError
from spidey.llm.domain.routing import ProviderName

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from spidey.llm.domain.chat import ChatRequest

_PROVIDER = ProviderName.ANTHROPIC.value

# Known models → manifest. An unlisted model gets sane, zero-priced defaults.
_CATALOG: dict[str, CapabilityManifest] = {
    "claude-sonnet-5": CapabilityManifest(
        provider=_PROVIDER,
        model="claude-sonnet-5",
        supports_tools=True,
        supports_streaming=True,
        max_context_tokens=200_000,
        input_price_per_mtok=3.0,
        output_price_per_mtok=15.0,
    ),
    "claude-haiku-4-5-20251001": CapabilityManifest(
        provider=_PROVIDER,
        model="claude-haiku-4-5-20251001",
        max_context_tokens=200_000,
        input_price_per_mtok=1.0,
        output_price_per_mtok=5.0,
    ),
}

_STOP_REASONS = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "tool_use": FinishReason.TOOL_USE,
    "max_tokens": FinishReason.LENGTH,
}


def _manifest(model: str) -> CapabilityManifest:
    return _CATALOG.get(model, CapabilityManifest(provider=_PROVIDER, model=model))


class AnthropicChatModel:
    def __init__(self, *, client: AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model
        self._manifest = _manifest(model)

    @property
    def manifest(self) -> CapabilityManifest:
        return self._manifest

    def _kwargs(self, request: ChatRequest) -> dict[str, Any]:
        system, messages = _to_anthropic(request.messages)
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if request.tools:
            kwargs["tools"] = _to_tools(request)
        return kwargs

    async def complete(self, request: ChatRequest) -> ChatResponse:
        try:
            message = cast("Any", await self._client.messages.create(**self._kwargs(request)))
        except Exception as exc:
            raise _translate(exc) from exc
        return self._to_response(message)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        try:
            async with self._client.messages.stream(**self._kwargs(request)) as stream:
                async for text in stream.text_stream:
                    yield ChatChunk(text_delta=text)
                final = cast("Any", await stream.get_final_message())
        except Exception as exc:
            raise _translate(exc) from exc
        response = self._to_response(final)
        for call in response.message.tool_calls:
            yield ChatChunk(tool_call=call)
        yield ChatChunk(usage=response.usage, finish_reason=response.finish_reason)

    def _to_response(self, message: Any) -> ChatResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
        return ChatResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT, content="".join(text_parts), tool_calls=tool_calls
            ),
            finish_reason=_STOP_REASONS.get(message.stop_reason, FinishReason.STOP),
            usage=Usage(
                prompt_tokens=message.usage.input_tokens,
                completion_tokens=message.usage.output_tokens,
            ),
            provider=_PROVIDER,
            model=self._model,
        )


class AnthropicFactory:
    """Owns the Anthropic client; builds a model-bound :class:`ChatModel`."""

    def __init__(self, *, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    def build(self, model: str) -> AnthropicChatModel:
        return AnthropicChatModel(client=self._client, model=model)


def _to_tools(request: ChatRequest) -> list[dict[str, object]]:
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in request.tools
    ]


def _to_anthropic(messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
    """Split system text out and render the rest as Anthropic message blocks."""
    system_parts: list[str] = []
    rendered: list[dict[str, Any]] = []
    for message in messages:
        if message.role is MessageRole.SYSTEM:
            system_parts.append(message.content)
        elif message.role is MessageRole.TOOL:
            rendered.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id,
                            "content": message.content,
                        }
                    ],
                }
            )
        elif message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                for c in message.tool_calls
            )
            rendered.append({"role": "assistant", "content": blocks})
        else:
            rendered.append({"role": message.role.value, "content": message.content})
    return "\n\n".join(system_parts), rendered


def _translate(exc: Exception) -> ProviderError:
    if isinstance(exc, APITimeoutError | APIConnectionError):
        return TransientProviderError("anthropic connection error", provider=_PROVIDER)
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        if status == 429 or status >= 500:  # noqa: PLR2004 — HTTP status codes
            return TransientProviderError("anthropic transient error", status=status)
        return ProviderError("anthropic request rejected", status=status)
    return ProviderError("anthropic error", detail_type=type(exc).__name__)
