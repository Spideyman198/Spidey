"""Workspace persistence models. Schema owned by Alembic migration 0002."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from spidey.platform.db import Base


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class WorkspaceRecord(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(16))
    location: Mapped[str] = mapped_column(String(2048))
    branch: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    head_commit: Mapped[str | None] = mapped_column(String(64))
    # Envelope-encrypted access token (opaque ciphertext string); null for local.
    encrypted_token: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class FileManifestRecord(Base):
    __tablename__ = "file_manifests"
    __table_args__ = (UniqueConstraint("workspace_id", "path", name="uq_file_manifests_ws_path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(String(4096))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    is_binary: Mapped[bool] = mapped_column(default=False)
    indexable: Mapped[bool] = mapped_column(default=True)
