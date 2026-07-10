"""Append-only audit plane (docs/09 §5).

Contract: audit records are security evidence, not telemetry — they are
written in the same database transaction as the action they describe, are
insert-only (enforced by a DB trigger, migration 0001), and never trimmed.
``details`` passes through the redaction scrubber before persistence, so an
audit row can never itself become a secret leak. Failures to write audit are
raised, not swallowed: an action that cannot be audited must not complete.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from spidey.platform.db import Base
from spidey.platform.security.scrubbing import scrub_event_dict

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class AuditAction(StrEnum):
    LOGIN_SUCCEEDED = "auth.login.succeeded"
    LOGIN_FAILED = "auth.login.failed"
    LOGIN_LOCKED_OUT = "auth.login.locked_out"
    TOKEN_REFRESHED = "auth.token.refreshed"
    TOKEN_REUSE_DETECTED = "auth.token.reuse_detected"
    LOGOUT = "auth.logout"
    PASSWORD_CHANGED = "auth.password.changed"
    USER_CREATED = "user.created"
    USER_DELETED = "user.deleted"
    AUTHZ_DENIED = "authz.denied"
    RATE_LIMITED = "request.rate_limited"
    SESSION_CREATED = "session.created"
    SESSION_DELETED = "session.deleted"
    WORKSPACE_CREATED = "workspace.created"
    WORKSPACE_DELETED = "workspace.deleted"
    WORKSPACE_INGESTED = "workspace.ingested"
    WORKSPACE_INGEST_FAILED = "workspace.ingest_failed"


class AuditLogRecord(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(tz=UTC), index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(16))  # success | failure | denied
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    target: Mapped[str | None] = mapped_column(String(256))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AuditSink(Protocol):
    """The write contract application services depend on, so both the
    transactional and independent loggers — and test fakes — are substitutable."""

    async def record(
        self,
        action: AuditAction,
        *,
        outcome: str,
        actor_user_id: uuid.UUID | None = None,
        target: str | None = None,
        source_ip: str | None = None,
        request_id: str | None = None,
        **details: Any,
    ) -> None: ...


def _build_record(
    action: AuditAction,
    *,
    outcome: str,
    actor_user_id: uuid.UUID | None,
    target: str | None,
    source_ip: str | None,
    request_id: str | None,
    details: dict[str, Any],
) -> AuditLogRecord:
    return AuditLogRecord(
        action=action.value,
        outcome=outcome,
        actor_user_id=actor_user_id,
        target=target,
        source_ip=source_ip,
        request_id=request_id,
        details=scrub_event_dict(None, "audit", details) if details else None,
    )


class AuditLogger:
    """Writes audit records inside the caller's transaction.

    Use for events that must be atomic with the action they describe — a
    successful action and its audit row commit or roll back together.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        action: AuditAction,
        *,
        outcome: str,
        actor_user_id: uuid.UUID | None = None,
        target: str | None = None,
        source_ip: str | None = None,
        request_id: str | None = None,
        **details: Any,
    ) -> None:
        self._session.add(
            _build_record(
                action,
                outcome=outcome,
                actor_user_id=actor_user_id,
                target=target,
                source_ip=source_ip,
                request_id=request_id,
                details=details,
            )
        )
        await self._session.flush()


class IndependentAuditLogger:
    """Writes audit records on their own committed transaction.

    Use for security-denial evidence (failed login, authz denial, token reuse)
    that must survive even though the request transaction rolls back. Opens a
    fresh session per record so it is never entangled with the request's
    unit of work.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        action: AuditAction,
        *,
        outcome: str,
        actor_user_id: uuid.UUID | None = None,
        target: str | None = None,
        source_ip: str | None = None,
        request_id: str | None = None,
        **details: Any,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                _build_record(
                    action,
                    outcome=outcome,
                    actor_user_id=actor_user_id,
                    target=target,
                    source_ip=source_ip,
                    request_id=request_id,
                    details=details,
                )
            )
            await session.commit()
