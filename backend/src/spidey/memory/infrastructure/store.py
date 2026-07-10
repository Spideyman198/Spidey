"""Postgres adapter for the conversation store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update

from spidey.memory.domain.models import ChatSession, Message, MessageAuthor
from spidey.memory.infrastructure.orm import MessageRecord, SessionRecord
from spidey.platform.db import affected_rows

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


def _to_session(record: SessionRecord) -> ChatSession:
    return ChatSession(
        id=record.id,
        owner_id=record.owner_id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _to_message(record: MessageRecord) -> Message:
    return Message(
        id=record.id,
        session_id=record.session_id,
        author=MessageAuthor(record.author),
        content=record.content,
        created_at=record.created_at,
    )


class PostgresConversationStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(self, *, owner_id: uuid.UUID, title: str) -> ChatSession:
        record = SessionRecord(owner_id=owner_id, title=title)
        self._session.add(record)
        await self._session.flush()
        return _to_session(record)

    async def get_session(
        self, *, owner_id: uuid.UUID, session_id: uuid.UUID
    ) -> ChatSession | None:
        record = await self._session.scalar(
            select(SessionRecord).where(
                SessionRecord.id == session_id, SessionRecord.owner_id == owner_id
            )
        )
        return None if record is None else _to_session(record)

    async def list_sessions(self, *, owner_id: uuid.UUID) -> list[ChatSession]:
        records = await self._session.scalars(
            select(SessionRecord)
            .where(SessionRecord.owner_id == owner_id)
            .order_by(SessionRecord.updated_at.desc())
        )
        return [_to_session(record) for record in records]

    async def rename_session(
        self, *, owner_id: uuid.UUID, session_id: uuid.UUID, title: str
    ) -> ChatSession | None:
        result = await self._session.execute(
            update(SessionRecord)
            .where(SessionRecord.id == session_id, SessionRecord.owner_id == owner_id)
            .values(title=title)
        )
        if not affected_rows(result):
            return None
        return await self.get_session(owner_id=owner_id, session_id=session_id)

    async def delete_session(self, *, owner_id: uuid.UUID, session_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            delete(SessionRecord).where(
                SessionRecord.id == session_id, SessionRecord.owner_id == owner_id
            )
        )
        return bool(affected_rows(result))

    async def add_message(
        self, *, session_id: uuid.UUID, author: MessageAuthor, content: str
    ) -> Message:
        record = MessageRecord(session_id=session_id, author=author.value, content=content)
        self._session.add(record)
        await self._session.flush()
        return _to_message(record)

    async def list_messages(
        self, *, session_id: uuid.UUID, limit: int, before: uuid.UUID | None
    ) -> list[Message]:
        query = (
            select(MessageRecord)
            .where(MessageRecord.session_id == session_id)
            .order_by(MessageRecord.created_at.desc(), MessageRecord.id.desc())
            .limit(limit)
        )
        if before is not None:
            anchor = await self._session.get(MessageRecord, before)
            if anchor is not None and anchor.session_id == session_id:
                query = query.where(MessageRecord.created_at < anchor.created_at)
        records = list(await self._session.scalars(query))
        records.reverse()  # chronological order for clients
        return [_to_message(record) for record in records]
