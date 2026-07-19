"""MemoryService — the long-term memory lifecycle (M11, docs/07 §3).

Owns the four operations that touch long-term memory: **write** (only ever
through the gate, so an imperative or a secret can never be persisted), **recall**
(scope-filtered semantic search returning attributed data), **feedback**
(reinforce/decay confidence from run outcomes), and **delete** (record *and*
vector, for user sovereignty). Agents never call write directly — distillation
and the explicit user 'remember this' do — which keeps memory from becoming an
injection-persistence channel.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spidey.memory.domain import (
    Memory,
    MemoryKind,
    RecalledMemory,
    decay,
    evaluate,
    reinforce,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spidey.memory.domain import MemoryCandidate, MemoryScope
    from spidey.memory.domain.ports import MemoryStore, MemoryVectorIndex, TextEmbedder

_ALL_KINDS = list(MemoryKind)


class MemoryService:
    def __init__(
        self,
        *,
        store: MemoryStore,
        vectors: MemoryVectorIndex,
        embedder: TextEmbedder,
    ) -> None:
        self._store = store
        self._vectors = vectors
        self._embedder = embedder

    async def write(self, candidates: Sequence[MemoryCandidate]) -> list[Memory]:
        """Screen every candidate through the write gate; store + index the ones
        that pass. Returns the accepted records (rejected candidates vanish)."""
        accepted: list[Memory] = []
        for candidate in candidates:
            existing = {
                m.content
                for m in await self._store.candidates(kinds=[candidate.kind], scope=candidate.scope)
            }
            existing.update(m.content for m in accepted if m.kind is candidate.kind)
            decision = evaluate(candidate, existing_contents=existing)
            if not decision.accepted:
                continue
            memory = Memory(
                id=uuid.uuid4(),
                kind=candidate.kind,
                scope=candidate.scope,
                content=decision.content,
                provenance=candidate.provenance,
                confidence=candidate.confidence,
                created_at=datetime.now(tz=UTC),
            )
            await self._store.create(memory)
            await self._vectors.upsert(
                memory_id=memory.id,
                vector=self._embedder.embed_query(memory.content),
                kind=memory.kind,
                scope=memory.scope,
            )
            accepted.append(memory)
        return accepted

    async def recall(
        self,
        *,
        query: str,
        kinds: list[MemoryKind],
        scope: MemoryScope,
        limit: int = 5,
    ) -> list[RecalledMemory]:
        """Scope-filtered semantic recall. Double-filtered by scope (the store's
        candidate pool *and* the vector search), so a scope leak needs both to
        fail."""
        pool = {m.id: m for m in await self._store.candidates(kinds=kinds, scope=scope)}
        if not pool:
            return []
        hits = await self._vectors.search(
            vector=self._embedder.embed_query(query), kinds=kinds, scope=scope, limit=limit
        )
        return [
            RecalledMemory(memory=pool[mid], similarity=score) for mid, score in hits if mid in pool
        ]

    async def record_feedback(self, recalled: Sequence[Memory], *, success: bool) -> None:
        """A run that recalled these memories succeeded (reinforce) or failed
        (decay) — so poisoned or stale memories die from evidence (docs/07 §3)."""
        now = datetime.now(tz=UTC)
        for memory in recalled:
            new_confidence = reinforce(memory.confidence) if success else decay(memory.confidence)
            await self._store.record_use(
                memory_id=memory.id, confidence=new_confidence, last_used_at=now
            )

    async def delete(self, *, user_id: uuid.UUID, memory_id: uuid.UUID) -> bool:
        """User sovereignty (FR-5.3): remove the record *and* its vector."""
        removed = await self._store.delete(user_id=user_id, memory_id=memory_id)
        if removed is None:
            return False
        await self._vectors.delete(memory_id=memory_id)
        return True

    async def list_for_user(self, *, user_id: uuid.UUID) -> list[Memory]:
        return await self._store.list_for_user(user_id=user_id)
