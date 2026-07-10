"""Conversation use cases with ownership enforcement and input bounds."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.memory.domain.models import (
    MESSAGE_MAX_CHARS,
    SESSION_TITLE_MAX_CHARS,
    MessageAuthor,
)
from spidey.platform.audit import AuditAction
from spidey.platform.errors import NotFoundError, ValidationFailedError

if TYPE_CHECKING:
    import uuid

    from spidey.memory.domain.models import ChatSession, Message
    from spidey.memory.domain.ports import ConversationStore
    from spidey.platform.audit import AuditSink

MESSAGE_PAGE_LIMIT_MAX = 200
_MISSING = "session does not exist"


def _validate_title(title: str) -> str:
    title = title.strip()
    if not title:
        raise ValidationFailedError("session title must not be empty")
    if len(title) > SESSION_TITLE_MAX_CHARS:
        raise ValidationFailedError(f"session title exceeds {SESSION_TITLE_MAX_CHARS} characters")
    return title


class ConversationService:
    def __init__(self, *, store: ConversationStore, audit: AuditSink) -> None:
        self._store = store
        self._audit = audit

    async def create_session(
        self, *, owner_id: uuid.UUID, title: str, request_id: str | None
    ) -> ChatSession:
        session = await self._store.create_session(owner_id=owner_id, title=_validate_title(title))
        await self._audit.record(
            AuditAction.SESSION_CREATED,
            outcome="success",
            actor_user_id=owner_id,
            target=str(session.id),
            request_id=request_id,
        )
        return session

    async def get_session(self, *, owner_id: uuid.UUID, session_id: uuid.UUID) -> ChatSession:
        session = await self._store.get_session(owner_id=owner_id, session_id=session_id)
        if session is None:
            raise NotFoundError(_MISSING)
        return session

    async def list_sessions(self, *, owner_id: uuid.UUID) -> list[ChatSession]:
        return await self._store.list_sessions(owner_id=owner_id)

    async def rename_session(
        self, *, owner_id: uuid.UUID, session_id: uuid.UUID, title: str
    ) -> ChatSession:
        session = await self._store.rename_session(
            owner_id=owner_id, session_id=session_id, title=_validate_title(title)
        )
        if session is None:
            raise NotFoundError(_MISSING)
        return session

    async def delete_session(
        self, *, owner_id: uuid.UUID, session_id: uuid.UUID, request_id: str | None
    ) -> None:
        deleted = await self._store.delete_session(owner_id=owner_id, session_id=session_id)
        if not deleted:
            raise NotFoundError(_MISSING)
        await self._audit.record(
            AuditAction.SESSION_DELETED,
            outcome="success",
            actor_user_id=owner_id,
            target=str(session_id),
            request_id=request_id,
        )

    async def add_user_message(
        self, *, owner_id: uuid.UUID, session_id: uuid.UUID, content: str
    ) -> Message:
        if not content.strip():
            raise ValidationFailedError("message content must not be empty")
        if len(content) > MESSAGE_MAX_CHARS:
            raise ValidationFailedError(f"message exceeds {MESSAGE_MAX_CHARS} characters")
        # Ownership check before write; the store's message ops are session-scoped.
        await self.get_session(owner_id=owner_id, session_id=session_id)
        return await self._store.add_message(
            session_id=session_id, author=MessageAuthor.USER, content=content
        )

    async def list_messages(
        self,
        *,
        owner_id: uuid.UUID,
        session_id: uuid.UUID,
        limit: int = 50,
        before: uuid.UUID | None = None,
    ) -> list[Message]:
        limit = max(1, min(limit, MESSAGE_PAGE_LIMIT_MAX))
        await self.get_session(owner_id=owner_id, session_id=session_id)
        return await self._store.list_messages(session_id=session_id, limit=limit, before=before)
