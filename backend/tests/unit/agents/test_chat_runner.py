"""End-to-end scripted-chat orchestration with real gateway + registry, fake
leaf adapters — the M6 exit-criterion plane, offline."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from spidey.agents.application import ChatRunner, ToolRegistry
from spidey.agents.domain import SideEffect, ToolResult, ToolSpec, TrustTier
from spidey.identity.domain.models import Role
from spidey.llm.application import Gateway, ProviderRegistry
from spidey.llm.domain import (
    CapabilityManifest,
    ChatMessage,
    ChatResponse,
    FinishReason,
    MessageRole,
    ProviderName,
    RouteConfig,
    ToolCall,
    Usage,
)
from spidey.llm.domain import (
    Role as ChatRole,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from spidey.agents.domain import ToolContext
    from spidey.llm.domain import ChatChunk, ChatRequest
    from spidey.platform.events import EventEnvelope


class ScriptedModel:
    """Returns a queued response per call — drives the tool round-trip."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = responses
        self._manifest = CapabilityManifest(provider="anthropic", model="m1")

    @property
    def manifest(self) -> CapabilityManifest:
        return self._manifest

    async def complete(self, request: ChatRequest) -> ChatResponse:
        return self._responses.pop(0)

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        raise NotImplementedError
        yield  # pragma: no cover


class Factory:
    def __init__(self, model: ScriptedModel) -> None:
        self._model = model

    def build(self, model: str) -> ScriptedModel:
        return self._model


class DemoProvider:
    def __init__(self) -> None:
        self.invoked = 0

    @property
    def namespace(self) -> str:
        return "demo"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="demo.search",
                description="search the workspace",
                input_schema={"type": "object"},
                side_effect=SideEffect.READ,
                trust_tier=TrustTier.TRUSTED,
                required_role=Role.VIEWER,
            )
        ]

    async def invoke(
        self, name: str, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        self.invoked += 1
        return ToolResult.success("tool says: found 3 matches")


class FakeEvents:
    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope] = []

    def add(self, envelope: EventEnvelope) -> None:
        self.envelopes.append(envelope)


class FakeStreamBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, stream_key: str, data: str) -> str:
        self.published.append((stream_key, data))
        return "1-0"


def _assistant_with_tool_call() -> ChatResponse:
    return ChatResponse(
        message=ChatMessage(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="c1", name="demo.search", arguments={"query": "auth"})],
        ),
        finish_reason=FinishReason.TOOL_USE,
        usage=Usage(prompt_tokens=10, completion_tokens=5),
        provider="anthropic",
        model="m1",
    )


def _final_answer() -> ChatResponse:
    return ChatResponse(
        message=ChatMessage(role=MessageRole.ASSISTANT, content="Here is what I found."),
        finish_reason=FinishReason.STOP,
        usage=Usage(prompt_tokens=20, completion_tokens=8),
        provider="anthropic",
        model="m1",
    )


async def test_chat_run_does_tool_round_trip_and_streams() -> None:
    model = ScriptedModel([_assistant_with_tool_call(), _final_answer()])
    llm_registry = ProviderRegistry(
        factories={ProviderName.ANTHROPIC: Factory(model)},
        routes={ChatRole.CHAT: RouteConfig(provider=ProviderName.ANTHROPIC, model="m1")},
    )
    events = FakeEvents()
    provider = DemoProvider()
    tools = ToolRegistry(providers=[provider], events=events)
    bus = FakeStreamBus()
    runner = ChatRunner(
        gateway=Gateway(registry=llm_registry, events=events),
        registry=tools,
        events=events,
        stream_bus=bus,  # type: ignore[arg-type]
    )

    run_id = uuid.uuid4()
    await runner.run(
        run_id=run_id,
        session_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        user_role=Role.DEVELOPER,
        message="where is auth handled?",
    )

    assert provider.invoked == 1  # the model's tool call was routed through the registry
    types = [e.event_type for e in events.envelopes]
    assert types == [
        "chat.message_received",  # user
        "llm.call_completed",  # round 1 (asked for a tool)
        "tools.invocation_started",
        "tools.invocation_completed",
        "llm.call_completed",  # round 2 (final answer)
        "chat.message_received",  # assistant
        "chat.run_completed",
    ]
    # The assistant reply was streamed to the run's SSE stream.
    assert len(bus.published) == 1
    assert bus.published[0][0] == f"run:{run_id}:events"
