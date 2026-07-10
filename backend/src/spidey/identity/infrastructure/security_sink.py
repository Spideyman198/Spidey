"""Independent-commit sink for security-denial events and reuse revocation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.identity.infrastructure.repositories import PostgresRefreshTokenRepository
from spidey.platform.audit import IndependentAuditLogger

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from spidey.platform.audit import AuditAction


class IndependentSecurityEventSink:
    """Each operation runs on its own fresh, immediately-committed session, so
    denial evidence and reuse revocation persist regardless of the request's
    unit-of-work rolling back."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._audit = IndependentAuditLogger(session_factory)

    async def record_denial(
        self,
        action: AuditAction,
        *,
        outcome: str,
        actor_user_id: uuid.UUID | None = None,
        target: str | None = None,
        source_ip: str | None = None,
        request_id: str | None = None,
        **details: object,
    ) -> None:
        await self._audit.record(
            action,
            outcome=outcome,
            actor_user_id=actor_user_id,
            target=target,
            source_ip=source_ip,
            request_id=request_id,
            **details,
        )

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        async with self._session_factory() as session:
            revoked = await PostgresRefreshTokenRepository(session).revoke_family(family_id)
            await session.commit()
            return revoked
