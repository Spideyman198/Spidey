"""LLM context ports — the provider seam and the gateway's collaborators.

``ChatModel`` is the provider-neutral seam (ADR-0009): three real adapters
implement it, and unit tests use a deterministic fake, so the whole agent graph
is testable offline. The gateway composes the other ports around it —
capture (replay), cache, budget — written once and applied to every provider.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from spidey.llm.domain.capabilities import CapabilityManifest
    from spidey.llm.domain.chat import ChatChunk, ChatRequest, ChatResponse, Usage
    from spidey.llm.domain.models import DenseVector, SparseVector


class DenseEmbedder(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[DenseVector]:
        """Embed a batch of documents. Order is preserved."""
        ...

    def embed_query(self, text: str) -> DenseVector: ...


class SparseEmbedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]: ...

    def embed_query(self, text: str) -> SparseVector: ...


class ChatModel(Protocol):
    """A single (provider, model) endpoint. Adapters normalize provider dialects
    behind this; callers reach it only through the gateway."""

    @property
    def manifest(self) -> CapabilityManifest: ...

    async def complete(self, request: ChatRequest) -> ChatResponse: ...

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]: ...


class InteractionCapture(Protocol):
    """Persists a redacted request/response pair for replay (docs/08 §5).

    Redaction happens at capture time — secrets never land on disk. Returns the
    ``interaction_id`` referenced from the ``LlmCallCompleted`` event."""

    async def record(
        self,
        *,
        provider: str,
        model: str,
        role: str,
        request: ChatRequest,
        response: ChatResponse,
        run_id: uuid.UUID | None,
    ) -> uuid.UUID: ...


class ResponseCache(Protocol):
    """Optional exact-match cache for deterministic (temperature 0, tool-free)
    completions. A miss returns None."""

    async def get(self, key: str) -> ChatResponse | None: ...

    async def put(self, key: str, response: ChatResponse) -> None: ...


class BudgetLedger(Protocol):
    """Per-scope (session/run) token + cost budget enforcement (NFR-5)."""

    async def would_exceed(self, scope: str, *, tokens: int) -> bool: ...

    async def record(self, scope: str, *, usage: Usage, cost_usd: float) -> None: ...
