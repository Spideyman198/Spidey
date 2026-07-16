"""OpenAI-compatible adapter — one adapter, four targets (ADR-0012).

Parameterized by base URL + key, it speaks the OpenAI Chat Completions dialect,
so OpenAI, Ollama, vLLM, and Azure OpenAI all ride behind the same ``ChatModel``.
Translates our chat types to/from OpenAI messages/tools, streams text (and
reassembles fragmented tool-call deltas), and maps failures to the gateway's
error taxonomy.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
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

_PROVIDER = ProviderName.OPENAI_COMPATIBLE.value

_CATALOG: dict[str, CapabilityManifest] = {
    "gpt-4o": CapabilityManifest(
        provider=_PROVIDER,
        model="gpt-4o",
        max_context_tokens=128_000,
        input_price_per_mtok=2.5,
        output_price_per_mtok=10.0,
    ),
    "gpt-4o-mini": CapabilityManifest(
        provider=_PROVIDER,
        model="gpt-4o-mini",
        max_context_tokens=128_000,
        input_price_per_mtok=0.15,
        output_price_per_mtok=0.6,
    ),
}

_FINISH = {
    "stop": FinishReason.STOP,
    "tool_calls": FinishReason.TOOL_USE,
    "length": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}


def _manifest(model: str) -> CapabilityManifest:
    # Self-hosted models (Ollama/vLLM) are unlisted → free, generous defaults.
    return _CATALOG.get(model, CapabilityManifest(provider=_PROVIDER, model=model))


class OpenAiCompatibleChatModel:
    def __init__(self, *, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model
        self._manifest = _manifest(model)

    @property
    def manifest(self) -> CapabilityManifest:
        return self._manifest

    def _kwargs(self, request: ChatRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": _to_openai(request.messages),
        }
        if request.tools:
            kwargs["tools"] = _to_tools(request)
        return kwargs

    async def complete(self, request: ChatRequest) -> ChatResponse:
        try:
            completion = cast(
                "Any", await self._client.chat.completions.create(**self._kwargs(request))
            )
        except Exception as exc:
            raise _translate(exc) from exc
        choice = completion.choices[0]
        return ChatResponse(
            message=_to_message(choice.message),
            finish_reason=_FINISH.get(choice.finish_reason, FinishReason.STOP),
            usage=_to_usage(completion.usage),
            provider=_PROVIDER,
            model=self._model,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        kwargs = self._kwargs(request)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        try:
            stream = cast("Any", await self._client.chat.completions.create(**kwargs))
            fragments: dict[int, dict[str, str]] = {}
            usage = Usage()
            finish = FinishReason.STOP
            async for chunk in stream:
                for choice in chunk.choices:
                    if choice.delta.content:
                        yield ChatChunk(text_delta=choice.delta.content)
                    _accumulate_tool_calls(choice.delta, fragments)
                    if choice.finish_reason:
                        finish = _FINISH.get(choice.finish_reason, FinishReason.STOP)
                if chunk.usage:
                    usage = _to_usage(chunk.usage)
        except Exception as exc:
            raise _translate(exc) from exc
        for call in _finish_tool_calls(fragments):
            yield ChatChunk(tool_call=call)
        yield ChatChunk(usage=usage, finish_reason=finish)


class OpenAiCompatibleFactory:
    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    def build(self, model: str) -> OpenAiCompatibleChatModel:
        return OpenAiCompatibleChatModel(client=self._client, model=model)


def _to_tools(request: ChatRequest) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in request.tools
    ]


def _to_openai(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.role is MessageRole.TOOL:
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )
        elif message.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in message.tool_calls
                    ],
                }
            )
        else:
            out.append({"role": message.role.value, "content": message.content})
    return out


def _to_message(message: Any) -> ChatMessage:
    tool_calls = [
        ToolCall(
            id=str(tc.id),
            name=str(tc.function.name),
            arguments=json.loads(cast("str", tc.function.arguments) or "{}"),
        )
        for tc in cast("list[Any]", message.tool_calls or [])
    ]
    return ChatMessage(
        role=MessageRole.ASSISTANT, content=message.content or "", tool_calls=tool_calls
    )


def _to_usage(usage: Any) -> Usage:
    if usage is None:
        return Usage()
    return Usage(prompt_tokens=usage.prompt_tokens, completion_tokens=usage.completion_tokens)


def _accumulate_tool_calls(delta: Any, fragments: dict[int, dict[str, str]]) -> None:
    for tc in cast("list[Any]", delta.tool_calls or []):
        frag = fragments.setdefault(int(tc.index), {"id": "", "name": "", "args": ""})
        if tc.id:
            frag["id"] = str(tc.id)
        if tc.function and tc.function.name:
            frag["name"] = str(tc.function.name)
        if tc.function and tc.function.arguments:
            frag["args"] += str(tc.function.arguments)


def _finish_tool_calls(fragments: dict[int, dict[str, str]]) -> list[ToolCall]:
    return [
        ToolCall(id=f["id"], name=f["name"], arguments=json.loads(f["args"] or "{}"))
        for f in fragments.values()
        if f["name"]
    ]


def _translate(exc: Exception) -> ProviderError:
    if isinstance(exc, APITimeoutError | APIConnectionError):
        return TransientProviderError("openai connection error", provider=_PROVIDER)
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        if status == 429 or status >= 500:  # noqa: PLR2004 — HTTP status codes
            return TransientProviderError("openai transient error", status=status)
        return ProviderError("openai request rejected", status=status)
    return ProviderError("openai error", detail_type=type(exc).__name__)
