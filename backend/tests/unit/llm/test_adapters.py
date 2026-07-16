"""Adapter translation (offline): exercised through the public ``complete`` with
a fake SDK client. The network path is covered by the key-gated conformance
suite; here we test the dialect translation — the real risk surface."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from spidey.llm.domain.chat import (
    ChatMessage,
    ChatRequest,
    FinishReason,
    MessageRole,
    ToolCall,
)
from spidey.llm.infrastructure.anthropic_adapter import AnthropicChatModel
from spidey.llm.infrastructure.openai_adapter import OpenAiCompatibleChatModel


def _conversation() -> list[ChatMessage]:
    return [
        ChatMessage.system("be helpful"),
        ChatMessage.user("find auth"),
        ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="t1", name="search", arguments={"q": "auth"})],
        ),
        ChatMessage.tool_result(tool_call_id="t1", name="search", content="found it"),
    ]


class FakeAnthropic:
    def __init__(self, message: object) -> None:
        self.messages = SimpleNamespace(create=self._create)
        self._message = message
        self.kwargs: dict[str, Any] = {}

    async def _create(self, **kwargs: Any) -> object:
        self.kwargs = kwargs
        return self._message


class FakeOpenAi:
    def __init__(self, completion: object) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._completion = completion
        self.kwargs: dict[str, Any] = {}

    async def _create(self, **kwargs: Any) -> object:
        self.kwargs = kwargs
        return self._completion


class TestAnthropic:
    async def test_request_translation_and_response_parsing(self) -> None:
        message = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="hello"),
                SimpleNamespace(type="tool_use", id="t9", name="grep", input={"p": "x"}),
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(input_tokens=12, output_tokens=4),
        )
        client = FakeAnthropic(message)
        model = AnthropicChatModel(client=cast("Any", client), model="claude-sonnet-5")
        response = await model.complete(ChatRequest(messages=_conversation()))

        # Request: system split out, tool_use + tool_result blocks rendered.
        assert client.kwargs["system"] == "be helpful"
        roles = [m["role"] for m in client.kwargs["messages"]]
        assert roles == ["user", "assistant", "user"]
        assert client.kwargs["messages"][2]["content"][0]["type"] == "tool_result"
        # Response: text + tool call + usage + finish reason.
        assert response.text == "hello"
        assert response.finish_reason is FinishReason.TOOL_USE
        assert response.message.tool_calls[0].name == "grep"
        assert response.usage.prompt_tokens == 12
        assert response.provider == "anthropic"


class TestOpenAi:
    async def test_request_translation_and_response_parsing(self) -> None:
        completion = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="hi",
                        tool_calls=[
                            SimpleNamespace(
                                id="c1",
                                function=SimpleNamespace(name="search", arguments='{"q": "x"}'),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2),
        )
        client = FakeOpenAi(completion)
        model = OpenAiCompatibleChatModel(client=cast("Any", client), model="gpt-4o-mini")
        response = await model.complete(ChatRequest(messages=_conversation()))

        mapped = client.kwargs["messages"]
        assert mapped[0] == {"role": "system", "content": "be helpful"}
        assert mapped[2]["tool_calls"][0]["function"]["name"] == "search"
        assert mapped[3]["role"] == "tool"
        assert response.finish_reason is FinishReason.TOOL_USE
        assert response.message.tool_calls[0].arguments == {"q": "x"}
        assert response.usage.prompt_tokens == 7

    def test_manifest_prices(self) -> None:
        known = OpenAiCompatibleChatModel(client=cast("Any", None), model="gpt-4o-mini")
        assert known.manifest.input_price_per_mtok > 0
        local = OpenAiCompatibleChatModel(client=cast("Any", None), model="llama3")
        assert local.manifest.input_price_per_mtok == 0.0
