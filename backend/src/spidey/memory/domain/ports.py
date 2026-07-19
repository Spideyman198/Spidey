"""Memory context ports (conversation slice + long-term memory)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid

    from spidey.memory.domain.longterm import Memory, MemoryKind, MemoryScope
    from spidey.memory.domain.models import ChatSession, Message, MessageAuthor


class ConversationStore(Protocol):
    """Persistence for sessions and messages. All lookups are owner-scoped —
    there is deliberately no unscoped accessor on this port."""

    async def create_session(self, *, owner_id: uuid.UUID, title: str) -> ChatSession: ...

    async def get_session(
        self, *, owner_id: uuid.UUID, session_id: uuid.UUID
    ) -> ChatSession | None: ...

    async def list_sessions(self, *, owner_id: uuid.UUID) -> list[ChatSession]: ...

    async def rename_session(
        self, *, owner_id: uuid.UUID, session_id: uuid.UUID, title: str
    ) -> ChatSession | None: ...

    async def delete_session(self, *, owner_id: uuid.UUID, session_id: uuid.UUID) -> bool: ...

    async def add_message(
        self,
        *,
        session_id: uuid.UUID,
        author: MessageAuthor,
        content: str,
    ) -> Message: ...

    async def list_messages(
        self,
        *,
        session_id: uuid.UUID,
        limit: int,
        before: uuid.UUID | None,
    ) -> list[Message]: ...


class MemoryStore(Protocol):
    """Persistence for long-term memory records (M11). Management lookups are
    user-scoped; recall candidate lookups are scope-filtered."""

    async def create(self, memory: Memory) -> None: ...

    async def get(self, *, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory | None:
        """User-scoped fetch for the management API (never cross-user)."""
        ...

    async def list_for_user(self, *, user_id: uuid.UUID, limit: int = 200) -> list[Memory]: ...

    async def candidates(
        self, *, kinds: list[MemoryKind], scope: MemoryScope, limit: int = 500
    ) -> list[Memory]:
        """Active memories visible under ``scope`` for the given kinds — the pool
        recall ranks and the write gate dedupes against."""
        ...

    async def record_use(
        self, *, memory_id: uuid.UUID, confidence: float, last_used_at: datetime
    ) -> None:
        """Update confidence + usage after outcome feedback (reinforce/decay)."""
        ...

    async def delete(self, *, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory | None:
        """Delete and return the removed record (for vector cleanup), or None."""
        ...


class MemoryVectorIndex(Protocol):
    """Semantic index over memory content (Qdrant ``memories`` collection).
    Deletion here is required so a user delete removes the vector too (FR-5.3)."""

    async def upsert(
        self,
        *,
        memory_id: uuid.UUID,
        vector: list[float],
        kind: MemoryKind,
        scope: MemoryScope,
    ) -> None: ...

    async def search(
        self,
        *,
        vector: list[float],
        kinds: list[MemoryKind],
        scope: MemoryScope,
        limit: int,
    ) -> list[tuple[uuid.UUID, float]]:
        """Scope-filtered nearest neighbors: (memory_id, similarity)."""
        ...

    async def delete(self, *, memory_id: uuid.UUID) -> None: ...


class TextEmbedder(Protocol):
    """Dense text embedding for memory content (structurally satisfied by the
    shared fastembed embedder; declared here so memory imports no other context)."""

    def embed_query(self, text: str) -> list[float]: ...
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
