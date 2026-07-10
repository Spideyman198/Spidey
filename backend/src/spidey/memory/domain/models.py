"""Conversation domain: sessions and their messages.

Ownership is a hard boundary: every read and write is scoped to the owner, and
a foreign session id behaves exactly like a nonexistent one (404, never 403 —
resource existence is not disclosed across users, admins included; operator
introspection needs go through the audit plane, not other people's chats).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

SESSION_TITLE_MAX_CHARS = 200
MESSAGE_MAX_CHARS = 32_768


class MessageAuthor(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"  # written by agent runs from M7
    SYSTEM = "system"


class ChatSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    session_id: uuid.UUID
    author: MessageAuthor
    content: str
    created_at: datetime
