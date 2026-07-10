"""API v1 request/response models.

These are the transport contract — deliberately separate from domain models so
the wire format can evolve independently and never leaks a field the domain
didn't intend (e.g. password hashes). Additive-only within v1 (docs/14 §8).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from spidey.identity.domain.models import Role
from spidey.memory.domain.models import MessageAuthor
from spidey.workspaces.domain.models import RepositorySource, WorkspaceStatus


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — scheme name
    expires_in: int


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    role: Role


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: Role
    is_active: bool
    created_at: datetime


class CreateSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32_768)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    author: MessageAuthor
    content: str
    created_at: datetime


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    source: RepositorySource
    location: str = Field(min_length=1, max_length=2048)
    branch: str | None = Field(default=None, max_length=255)
    # Transient: envelope-encrypted before storage, never echoed back.
    token: str | None = Field(default=None, max_length=512)


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    source: RepositorySource
    location: str
    branch: str | None
    status: WorkspaceStatus
    head_commit: str | None
    size_bytes: int
    file_count: int
    error: str | None
    created_at: datetime
    updated_at: datetime


class FileManifestEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    path: str
    sha256: str
    size_bytes: int
    is_binary: bool
    indexable: bool
