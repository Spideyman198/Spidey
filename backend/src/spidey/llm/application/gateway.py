"""The LLM gateway — the one seam every model call passes through (ADR-0009).

Around the provider-neutral :class:`ChatModel` it layers, in order: budget
enforcement, exact-match caching (deterministic calls only), a retry-with-
backoff + fallback-chain walk, usage metering (a ``LlmCallCompleted`` event),
and redacted capture for replay. Written once here, it applies to every provider
— agents cannot bypass budgets or metering because they never hold an adapter.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from typing import TYPE_CHECKING

from spidey.llm.domain.chat import (
    ChatMessage,
    ChatResponse,
    FinishReason,
    MessageRole,
    Usage,
)
from spidey.llm.domain.errors import (
    AllProvidersFailedError,
    BudgetExceededError,
    ProviderError,
    TransientProviderError,
)
from spidey.platform.events import EventEnvelope, LlmCallCompleted
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncIterator

    from spidey.llm.application.registry import ProviderRegistry
    from spidey.llm.domain.chat import ChatChunk, ChatRequest, Role
    from spidey.llm.domain.ports import (
        BudgetLedger,
        ChatModel,
        InteractionCapture,
        ResponseCache,
    )
    from spidey.platform.events import EventPublisher

_logger = get_logger("spidey.llm.gateway")


class Gateway:
    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        events: EventPublisher | None = None,
        capture: InteractionCapture | None = None,
        cache: ResponseCache | None = None,
        budget: BudgetLedger | None = None,
        max_retries: int = 2,
        backoff_base_seconds: float = 0.5,
    ) -> None:
        self._registry = registry
        self._events = events
        self._capture = capture
        self._cache = cache
        self._budget = budget
        self._max_retries = max_retries
        self._backoff = backoff_base_seconds

    async def complete(
        self,
        *,
        role: Role,
        request: ChatRequest,
        run_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        actor: str | None = None,
        budget_scope: str | None = None,
    ) -> ChatResponse:
        await self._check_budget(budget_scope, request)

        cache_key = self._cache_key(role, request)
        if cache_key is not None and self._cache is not None:
            hit = await self._cache.get(cache_key)
            if hit is not None:
                await self._meter(hit, role, run_id, session_id, actor, cached=True)
                return hit

        started = time.perf_counter()
        response, model = await self._invoke_chain(role, request)
        latency_ms = int((time.perf_counter() - started) * 1000)

        await self._settle(
            response=response,
            model=model,
            role=role,
            request=request,
            latency_ms=latency_ms,
            run_id=run_id,
            session_id=session_id,
            actor=actor,
            budget_scope=budget_scope,
        )
        if cache_key is not None and self._cache is not None:
            await self._cache.put(cache_key, response)
        return response

    async def stream(
        self,
        *,
        role: Role,
        request: ChatRequest,
        run_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        actor: str | None = None,
        budget_scope: str | None = None,
    ) -> AsyncIterator[ChatChunk]:
        """Stream deltas, then meter/capture the assembled response on completion.

        Fallback applies to establishing the stream, not mid-stream (a partially
        delivered stream cannot be replayed on another provider)."""
        await self._check_budget(budget_scope, request)
        model = self._first_model(role)
        started = time.perf_counter()
        chunks: list[ChatChunk] = []
        async for chunk in model.stream(request):
            chunks.append(chunk)
            yield chunk
        latency_ms = int((time.perf_counter() - started) * 1000)
        response = _assemble(chunks, model)
        await self._settle(
            response=response,
            model=model,
            role=role,
            request=request,
            latency_ms=latency_ms,
            run_id=run_id,
            session_id=session_id,
            actor=actor,
            budget_scope=budget_scope,
        )

    # ── internals ────────────────────────────────────────────────────────────
    async def _invoke_chain(
        self, role: Role, request: ChatRequest
    ) -> tuple[ChatResponse, ChatModel]:
        last_error: ProviderError | None = None
        for model in self._registry.chain(role):
            for attempt in range(self._max_retries + 1):
                try:
                    return await model.complete(request), model
                except TransientProviderError as exc:
                    last_error = exc
                    if attempt < self._max_retries:
                        await _sleep(self._backoff, attempt)
                        continue
                except ProviderError as exc:
                    last_error = exc
                    break  # non-transient: don't retry this model, try the next
        msg = f"all providers failed for role {role.value!r}"
        raise AllProvidersFailedError(msg, role=role.value) from last_error

    def _first_model(self, role: Role) -> ChatModel:
        return self._registry.chain(role)[0]

    async def _check_budget(self, scope: str | None, request: ChatRequest) -> None:
        if (
            self._budget is not None
            and scope is not None
            and await self._budget.would_exceed(scope, tokens=request.max_tokens)
        ):
            msg = f"budget exceeded for scope {scope!r}"
            raise BudgetExceededError(msg, scope=scope)

    async def _settle(
        self,
        *,
        response: ChatResponse,
        model: ChatModel,
        role: Role,
        request: ChatRequest,
        latency_ms: int,
        run_id: uuid.UUID | None,
        session_id: uuid.UUID | None,
        actor: str | None,
        budget_scope: str | None,
    ) -> None:
        cost = model.manifest.cost(response.usage)
        interaction_id: uuid.UUID | None = None
        if self._capture is not None:
            interaction_id = await self._capture.record(
                provider=response.provider,
                model=response.model,
                role=role.value,
                request=request,
                response=response,
                run_id=run_id,
            )
        await self._meter(
            response,
            role,
            run_id,
            session_id,
            actor,
            cost=cost,
            latency_ms=latency_ms,
            interaction_id=interaction_id,
        )
        if self._budget is not None and budget_scope is not None:
            await self._budget.record(budget_scope, usage=response.usage, cost_usd=cost)

    async def _meter(
        self,
        response: ChatResponse,
        role: Role,
        run_id: uuid.UUID | None,
        session_id: uuid.UUID | None,
        actor: str | None,
        *,
        cost: float = 0.0,
        latency_ms: int = 0,
        interaction_id: uuid.UUID | None = None,
        cached: bool = False,
    ) -> None:
        if self._events is None:
            return
        self._events.add(
            EventEnvelope.of(
                LlmCallCompleted(
                    provider=response.provider,
                    model=response.model,
                    role=role.value,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    latency_ms=latency_ms,
                    cost_usd=cost,
                    interaction_id=interaction_id,
                    cached=cached,
                ),
                run_id=run_id,
                session_id=session_id,
                actor=actor,
            )
        )

    def _cache_key(self, role: Role, request: ChatRequest) -> str | None:
        # Only deterministic, tool-free calls are cacheable.
        if request.temperature != 0.0 or request.tools:
            return None
        primary = self._registry.route(role).primary
        blob = json.dumps(
            {
                "provider": primary.provider.value,
                "model": primary.model,
                "max_tokens": request.max_tokens,
                "messages": [m.model_dump(mode="json") for m in request.messages],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return "llm:cache:" + hashlib.sha256(blob.encode()).hexdigest()


def _assemble(chunks: list[ChatChunk], model: ChatModel) -> ChatResponse:
    text = "".join(c.text_delta for c in chunks)
    tool_calls = [c.tool_call for c in chunks if c.tool_call is not None]
    usage = next((c.usage for c in reversed(chunks) if c.usage is not None), Usage())
    finish = next(
        (c.finish_reason for c in reversed(chunks) if c.finish_reason is not None),
        FinishReason.STOP,
    )
    return ChatResponse(
        message=ChatMessage(role=MessageRole.ASSISTANT, content=text, tool_calls=tool_calls),
        finish_reason=finish,
        usage=usage,
        provider=model.manifest.provider,
        model=model.manifest.model,
    )


async def _sleep(base: float, attempt: int) -> None:
    delay = base * (2**attempt) + random.uniform(0, base)  # noqa: S311 — jitter, not crypto
    await asyncio.sleep(delay)
