"""Memory context ports (conversation slice)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid

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
