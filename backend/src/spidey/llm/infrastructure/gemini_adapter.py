"""Gemini adapter — native SDK (ADR-0012).

Gemini's dialect is the most divergent: ``model`` (not ``assistant``) turns,
system text in ``system_instruction``, and tool calls/results as ``function_call``
/ ``function_response`` parts. Normalizing it here is exactly the "tool-calling
dialect differences are ours to normalize" cost the ADR accepts — bounded by the
conformance suite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

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

_PROVIDER = ProviderName.GEMINI.value

_CATALOG: dict[str, CapabilityManifest] = {
    "gemini-2.0-flash": CapabilityManifest(
        provider=_PROVIDER,
        model="gemini-2.0-flash",
        max_context_tokens=1_000_000,
        input_price_per_mtok=0.1,
        output_price_per_mtok=0.4,
    ),
}


def _manifest(model: str) -> CapabilityManifest:
    return _CATALOG.get(model, CapabilityManifest(provider=_PROVIDER, model=model))


class GeminiChatModel:
    def __init__(self, *, client: genai.Client, model: str) -> None:
        self._client = client
        self._model = model
        self._manifest = _manifest(model)

    @property
    def manifest(self) -> CapabilityManifest:
        return self._manifest

    def _config(self, request: ChatRequest, system: str) -> genai_types.GenerateContentConfig:
        tools = None
        if request.tools:
            tools = [
                genai_types.Tool(
                    function_declarations=[
                        genai_types.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters=cast("Any", t.input_schema),
                        )
                        for t in request.tools
                    ]
                )
            ]
        return genai_types.GenerateContentConfig(
            system_instruction=system or None,
            tools=cast("Any", tools),
            max_output_tokens=request.max_tokens,
            temperature=request.temperature,
        )

    async def complete(self, request: ChatRequest) -> ChatResponse:
        system, contents = _to_contents(request.messages)
        try:
            response = cast(
                "Any",
                await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=cast("Any", contents),
                    config=self._config(request, system),
                ),
            )
        except Exception as exc:
            raise _translate(exc) from exc
        return self._to_response(response)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        system, contents = _to_contents(request.messages)
        try:
            stream = await self._client.aio.models.generate_content_stream(
                model=self._model,
                contents=cast("Any", contents),
                config=self._config(request, system),
            )
            final = None
            async for chunk in cast("Any", stream):
                if chunk.text:
                    yield ChatChunk(text_delta=chunk.text)
                final = chunk
        except Exception as exc:
            raise _translate(exc) from exc
        if final is not None:
            response = self._to_response(final)
            for call in response.message.tool_calls:
                yield ChatChunk(tool_call=call)
            yield ChatChunk(usage=response.usage, finish_reason=response.finish_reason)

    def _to_response(self, response: Any) -> ChatResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        candidates = cast("list[Any]", response.candidates or [])
        if candidates and candidates[0].content and candidates[0].content.parts:
            for part in cast("list[Any]", candidates[0].content.parts):
                if getattr(part, "text", None):
                    text_parts.append(str(part.text))
                if getattr(part, "function_call", None):
                    fc = part.function_call
                    tool_calls.append(
                        ToolCall(
                            id=str(fc.name),
                            name=str(fc.name),
                            arguments=cast("dict[str, object]", dict(fc.args) if fc.args else {}),
                        )
                    )
        finish = FinishReason.TOOL_USE if tool_calls else FinishReason.STOP
        return ChatResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT, content="".join(text_parts), tool_calls=tool_calls
            ),
            finish_reason=finish,
            usage=_to_usage(response.usage_metadata),
            provider=_PROVIDER,
            model=self._model,
        )


class GeminiFactory:
    def __init__(self, *, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    def build(self, model: str) -> GeminiChatModel:
        return GeminiChatModel(client=self._client, model=model)


def _to_contents(messages: list[ChatMessage]) -> tuple[str, list[genai_types.Content]]:
    system_parts: list[str] = []
    contents: list[genai_types.Content] = []
    for message in messages:
        if message.role is MessageRole.SYSTEM:
            system_parts.append(message.content)
        elif message.role is MessageRole.TOOL:
            contents.append(
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part.from_function_response(
                            name=message.name or "tool", response={"result": message.content}
                        )
                    ],
                )
            )
        elif message.tool_calls:
            parts: list[genai_types.Part] = []
            if message.content:
                parts.append(genai_types.Part(text=message.content))
            parts.extend(
                genai_types.Part(
                    function_call=genai_types.FunctionCall(name=c.name, args=c.arguments)
                )
                for c in message.tool_calls
            )
            contents.append(genai_types.Content(role="model", parts=parts))
        else:
            role = "model" if message.role is MessageRole.ASSISTANT else "user"
            contents.append(
                genai_types.Content(role=role, parts=[genai_types.Part(text=message.content)])
            )
    return "\n\n".join(system_parts), contents


def _to_usage(metadata: Any) -> Usage:
    if metadata is None:
        return Usage()
    return Usage(
        prompt_tokens=metadata.prompt_token_count or 0,
        completion_tokens=metadata.candidates_token_count or 0,
    )


def _translate(exc: Exception) -> ProviderError:
    if isinstance(exc, genai_errors.ServerError):
        return TransientProviderError("gemini server error", provider=_PROVIDER)
    if isinstance(exc, genai_errors.ClientError):
        code = getattr(exc, "code", 400)
        if code == 429:  # noqa: PLR2004 — rate limited
            return TransientProviderError("gemini rate limited", status=code)
        return ProviderError("gemini request rejected", status=code)
    return ProviderError("gemini error", detail_type=type(exc).__name__)
