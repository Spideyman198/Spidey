"""Per-adapter conformance (ADR-0012): each configured provider must complete,
stream, account usage, and round-trip a tool call. Skips a provider with no key,
so "switching requires configuration only" is a tested property in CI when keys
are present — never a slogan, never a hard failure without credentials.
"""

from __future__ import annotations

import os

import pytest

from spidey.llm.domain.chat import ChatMessage, ChatRequest, FinishReason, ToolSchema

pytestmark = pytest.mark.integration

_WEATHER_TOOL = ToolSchema(
    name="get_weather",
    description="Get the current temperature for a city.",
    input_schema={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
)


def _anthropic():
    from spidey.llm.infrastructure import AnthropicFactory

    key = os.environ.get("SPIDEY_ANTHROPIC_API_KEY")
    return AnthropicFactory(api_key=key).build("claude-sonnet-5") if key else None


def _openai():
    from spidey.llm.infrastructure import OpenAiCompatibleFactory

    key = os.environ.get("SPIDEY_OPENAI_API_KEY")
    base = os.environ.get("SPIDEY_OPENAI_BASE_URL")
    return OpenAiCompatibleFactory(api_key=key, base_url=base).build("gpt-4o-mini") if key else None


def _gemini():
    from spidey.llm.infrastructure import GeminiFactory

    key = os.environ.get("SPIDEY_GEMINI_API_KEY")
    return GeminiFactory(api_key=key).build("gemini-2.0-flash") if key else None


_MODELS = {"anthropic": _anthropic, "openai": _openai, "gemini": _gemini}


def _model(name: str):
    model = _MODELS[name]()
    if model is None:
        pytest.skip(f"no {name} API key configured")
    return model


@pytest.mark.parametrize("provider", list(_MODELS))
class TestConformance:
    async def test_completes_and_accounts_usage(self, provider: str) -> None:
        model = _model(provider)
        response = await model.complete(
            ChatRequest(
                messages=[ChatMessage.user("Reply with exactly the word: ok")],
                max_tokens=16,
            )
        )
        assert response.text.strip()
        assert response.usage.total_tokens > 0
        assert response.model

    async def test_streams_text(self, provider: str) -> None:
        model = _model(provider)
        chunks = [
            chunk
            async for chunk in model.stream(
                ChatRequest(messages=[ChatMessage.user("Count: 1 2 3")], max_tokens=32)
            )
        ]
        assert "".join(c.text_delta for c in chunks).strip()
        assert any(c.usage is not None for c in chunks)

    async def test_tool_call_round_trip(self, provider: str) -> None:
        model = _model(provider)
        response = await model.complete(
            ChatRequest(
                messages=[ChatMessage.user("What's the weather in Paris? Use the tool.")],
                tools=[_WEATHER_TOOL],
                max_tokens=256,
            )
        )
        assert response.finish_reason is FinishReason.TOOL_USE
        assert response.message.tool_calls
        call = response.message.tool_calls[0]
        assert call.name == "get_weather"
        assert "city" in call.arguments
