"""ConversationService: ownership scoping, validation, pagination bounds."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from spidey.memory.application import ConversationService
from spidey.memory.domain.models import ChatSession, Message, MessageAuthor
from spidey.platform.errors import NotFoundError, ValidationFailedError


class FakeConversationStore:
    def __init__(self) -> None:
        self.sessions: dict[uuid.UUID, ChatSession] = {}
        self.messages: dict[uuid.UUID, list[Message]] = {}

    async def create_session(self, *, owner_id: uuid.UUID, title: str) -> ChatSession:
        now = datetime.now(tz=UTC)
        session = ChatSession(
            id=uuid.uuid4(), owner_id=owner_id, title=title, created_at=now, updated_at=now
        )
        self.sessions[session.id] = session
        self.messages[session.id] = []
        return session

    async def get_session(
        self, *, owner_id: uuid.UUID, session_id: uuid.UUID
    ) -> ChatSession | None:
        s = self.sessions.get(session_id)
        return s if s is not None and s.owner_id == owner_id else None

    async def list_sessions(self, *, owner_id: uuid.UUID) -> list[ChatSession]:
        return [s for s in self.sessions.values() if s.owner_id == owner_id]

    async def rename_session(
        self, *, owner_id: uuid.UUID, session_id: uuid.UUID, title: str
    ) -> ChatSession | None:
        s = await self.get_session(owner_id=owner_id, session_id=session_id)
        if s is None:
            return None
        updated = s.model_copy(update={"title": title})
        self.sessions[session_id] = updated
        return updated

    async def delete_session(self, *, owner_id: uuid.UUID, session_id: uuid.UUID) -> bool:
        if await self.get_session(owner_id=owner_id, session_id=session_id) is None:
            return False
        del self.sessions[session_id]
        return True

    async def add_message(
        self, *, session_id: uuid.UUID, author: MessageAuthor, content: str
    ) -> Message:
        msg = Message(
            id=uuid.uuid4(),
            session_id=session_id,
            author=author,
            content=content,
            created_at=datetime.now(tz=UTC),
        )
        self.messages[session_id].append(msg)
        return msg

    async def list_messages(
        self, *, session_id: uuid.UUID, limit: int, before: uuid.UUID | None
    ) -> list[Message]:
        return self.messages[session_id][:limit]


class FakeAuditLogger:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def record(self, action: Any, *, outcome: str, **details: Any) -> None:
        self.events.append(action.value)


@pytest.fixture
def service() -> ConversationService:
    return ConversationService(store=FakeConversationStore(), audit=FakeAuditLogger())


OWNER = uuid.uuid4()
OTHER = uuid.uuid4()


class TestOwnershipScoping:
    async def test_other_user_session_is_not_found(self, service: ConversationService) -> None:
        session = await service.create_session(owner_id=OWNER, title="mine", request_id=None)
        with pytest.raises(NotFoundError):
            await service.get_session(owner_id=OTHER, session_id=session.id)

    async def test_list_is_scoped_to_owner(self, service: ConversationService) -> None:
        await service.create_session(owner_id=OWNER, title="a", request_id=None)
        await service.create_session(owner_id=OTHER, title="b", request_id=None)
        assert len(await service.list_sessions(owner_id=OWNER)) == 1

    async def test_delete_other_users_session_is_not_found(
        self, service: ConversationService
    ) -> None:
        session = await service.create_session(owner_id=OWNER, title="mine", request_id=None)
        with pytest.raises(NotFoundError):
            await service.delete_session(owner_id=OTHER, session_id=session.id, request_id=None)

    async def test_cannot_add_message_to_others_session(self, service: ConversationService) -> None:
        session = await service.create_session(owner_id=OWNER, title="mine", request_id=None)
        with pytest.raises(NotFoundError):
            await service.add_user_message(owner_id=OTHER, session_id=session.id, content="hello")


class TestValidation:
    async def test_empty_title_rejected(self, service: ConversationService) -> None:
        with pytest.raises(ValidationFailedError):
            await service.create_session(owner_id=OWNER, title="   ", request_id=None)

    async def test_overlong_title_rejected(self, service: ConversationService) -> None:
        with pytest.raises(ValidationFailedError):
            await service.create_session(owner_id=OWNER, title="x" * 201, request_id=None)

    async def test_empty_message_rejected(self, service: ConversationService) -> None:
        session = await service.create_session(owner_id=OWNER, title="s", request_id=None)
        with pytest.raises(ValidationFailedError):
            await service.add_user_message(owner_id=OWNER, session_id=session.id, content="  ")

    async def test_message_records_as_user_author(self, service: ConversationService) -> None:
        session = await service.create_session(owner_id=OWNER, title="s", request_id=None)
        msg = await service.add_user_message(owner_id=OWNER, session_id=session.id, content="hi")
        assert msg.author is MessageAuthor.USER

    async def test_message_limit_is_clamped(self, service: ConversationService) -> None:
        session = await service.create_session(owner_id=OWNER, title="s", request_id=None)
        # Over-max limit must not raise; it clamps.
        result = await service.list_messages(owner_id=OWNER, session_id=session.id, limit=10_000)
        assert result == []
