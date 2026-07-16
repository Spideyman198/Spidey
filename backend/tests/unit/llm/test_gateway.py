"""Gateway middleware against a deterministic fake ChatModel (ADR-0009):
retry, fallback, metering, caching, and budget — all offline."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from spidey.llm.application import Gateway, ProviderRegistry
from spidey.llm.domain import (
    CapabilityManifest,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FinishReason,
    MessageRole,
    ModelRef,
    ProviderName,
    Role,
    RouteConfig,
    Usage,
)
from spidey.llm.domain.errors import (
    AllProvidersFailedError,
    BudgetExceededError,
    TransientProviderError,
)
from spidey.platform.events import EventEnvelope, LlmCallCompleted

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from spidey.llm.domain.chat import ChatChunk


def _manifest(model: str) -> CapabilityManifest:
    return CapabilityManifest(
        provider="anthropic",
        model=model,
        input_price_per_mtok=3.0,
        output_price_per_mtok=15.0,
    )


def _response(model: str, text: str = "hi") -> ChatResponse:
    return ChatResponse(
        message=ChatMessage(role=MessageRole.ASSISTANT, content=text),
        finish_reason=FinishReason.STOP,
        usage=Usage(prompt_tokens=1000, completion_tokens=500),
        provider="anthropic",
        model=model,
    )


class FakeChatModel:
    def __init__(
        self,
        model: str,
        *,
        errors: Sequence[Exception] | None = None,
        response: ChatResponse | None = None,
        chunks: Sequence[ChatChunk] | None = None,
    ) -> None:
        self._manifest = _manifest(model)
        self._errors = list(errors or [])
        self._response = response or _response(model)
        self._chunks = chunks or []
        self.calls = 0

    @property
    def manifest(self) -> CapabilityManifest:
        return self._manifest

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        return self._response

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        self.calls += 1
        for chunk in self._chunks:
            yield chunk


class FakeFactory:
    def __init__(self, models: dict[str, FakeChatModel]) -> None:
        self._models = models

    def build(self, model: str) -> FakeChatModel:
        return self._models[model]


class FakeEvents:
    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope] = []

    def add(self, envelope: EventEnvelope) -> None:
        self.envelopes.append(envelope)


class FakeCache:
    def __init__(self, hit: ChatResponse | None = None) -> None:
        self.hit = hit
        self.puts: list[str] = []

    async def get(self, key: str) -> ChatResponse | None:
        return self.hit

    async def put(self, key: str, response: ChatResponse) -> None:
        self.puts.append(key)


class FakeBudget:
    def __init__(self, *, exceed: bool = False) -> None:
        self.exceed = exceed
        self.recorded: list[float] = []

    async def would_exceed(self, scope: str, *, tokens: int) -> bool:
        return self.exceed

    async def record(self, scope: str, *, usage: Usage, cost_usd: float) -> None:
        self.recorded.append(cost_usd)


def _registry(
    models: dict[str, FakeChatModel], *, fallbacks: list[str] | None = None
) -> ProviderRegistry:
    route = RouteConfig(
        provider=ProviderName.ANTHROPIC,
        model=next(iter(models)),
        fallbacks=[ModelRef(provider=ProviderName.ANTHROPIC, model=m) for m in (fallbacks or [])],
    )
    return ProviderRegistry(
        factories={ProviderName.ANTHROPIC: FakeFactory(models)},
        routes={Role.CHAT: route},
    )


def _request() -> ChatRequest:
    return ChatRequest(messages=[ChatMessage.user("hello")], temperature=0.7)


def _only(events: FakeEvents) -> LlmCallCompleted:
    assert len(events.envelopes) == 1
    payload = events.envelopes[0].validated_payload()
    assert isinstance(payload, LlmCallCompleted)
    return payload


class TestGateway:
    async def test_completes_and_meters(self) -> None:
        model = FakeChatModel("m1")
        events = FakeEvents()
        gw = Gateway(registry=_registry({"m1": model}), events=events)
        response = await gw.complete(role=Role.CHAT, request=_request())
        assert response.text == "hi"
        meter = _only(events)
        assert meter.model == "m1"
        assert meter.prompt_tokens == 1000
        # cost = (1000*3 + 500*15) / 1e6
        assert meter.cost_usd == pytest.approx(0.0105)
        assert meter.cached is False

    async def test_retries_transient_then_succeeds(self) -> None:
        model = FakeChatModel("m1", errors=[TransientProviderError("429")])
        gw = Gateway(registry=_registry({"m1": model}), backoff_base_seconds=0.0)
        response = await gw.complete(role=Role.CHAT, request=_request())
        assert response.text == "hi"
        assert model.calls == 2  # one failure + one success

    async def test_falls_back_to_next_model(self) -> None:
        primary = FakeChatModel("m1", errors=[TransientProviderError("x")] * 3)
        secondary = FakeChatModel("m2", response=_response("m2", "from-fallback"))
        gw = Gateway(
            registry=_registry({"m1": primary, "m2": secondary}, fallbacks=["m2"]),
            backoff_base_seconds=0.0,
        )
        response = await gw.complete(role=Role.CHAT, request=_request())
        assert response.text == "from-fallback"
        assert response.model == "m2"

    async def test_all_providers_failing_raises(self) -> None:
        primary = FakeChatModel("m1", errors=[TransientProviderError("x")] * 3)
        gw = Gateway(registry=_registry({"m1": primary}), backoff_base_seconds=0.0)
        with pytest.raises(AllProvidersFailedError):
            await gw.complete(role=Role.CHAT, request=_request())

    async def test_cache_hit_short_circuits(self) -> None:
        model = FakeChatModel("m1")
        cache = FakeCache(hit=_response("m1", "cached"))
        events = FakeEvents()
        gw = Gateway(registry=_registry({"m1": model}), cache=cache, events=events)
        # Deterministic (temp 0, no tools) request is cacheable.
        request = ChatRequest(messages=[ChatMessage.user("hello")], temperature=0.0)
        response = await gw.complete(role=Role.CHAT, request=request)
        assert response.text == "cached"
        assert model.calls == 0  # served from cache
        assert _only(events).cached is True

    async def test_budget_exceeded_blocks_call(self) -> None:
        model = FakeChatModel("m1")
        gw = Gateway(registry=_registry({"m1": model}), budget=FakeBudget(exceed=True))
        with pytest.raises(BudgetExceededError):
            await gw.complete(role=Role.CHAT, request=_request(), budget_scope="session:1")
        assert model.calls == 0

    async def test_budget_recorded_after_call(self) -> None:
        budget = FakeBudget()
        gw = Gateway(registry=_registry({"m1": FakeChatModel("m1")}), budget=budget)
        await gw.complete(role=Role.CHAT, request=_request(), budget_scope="session:1")
        assert budget.recorded == [pytest.approx(0.0105)]

    async def test_stream_assembles_and_meters(self) -> None:
        from spidey.llm.domain.chat import ChatChunk

        chunks = [
            ChatChunk(text_delta="hel"),
            ChatChunk(text_delta="lo"),
            ChatChunk(
                usage=Usage(prompt_tokens=10, completion_tokens=2), finish_reason=FinishReason.STOP
            ),
        ]
        model = FakeChatModel("m1", chunks=chunks)
        events = FakeEvents()
        gw = Gateway(registry=_registry({"m1": model}), events=events)
        collected = [c async for c in gw.stream(role=Role.CHAT, request=_request())]
        assert "".join(c.text_delta for c in collected) == "hello"
        meter = _only(events)
        assert meter.completion_tokens == 2
