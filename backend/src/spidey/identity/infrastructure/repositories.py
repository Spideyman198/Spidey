"""Postgres adapters for the identity repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from spidey.identity.domain.models import Role, User
from spidey.identity.infrastructure.orm import RefreshTokenRecord, UserRecord
from spidey.platform.db import affected_rows
from spidey.platform.errors import ConflictError

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


def _to_user(record: UserRecord) -> User:
    return User(
        id=record.id,
        email=record.email,
        role=Role(record.role),
        is_active=record.is_active,
        created_at=record.created_at,
    )


@dataclass(frozen=True)
class _StoredUser:
    user: User
    password_hash: str


class PostgresUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> _StoredUser | None:
        record = await self._session.scalar(select(UserRecord).where(UserRecord.email == email))
        return None if record is None else _StoredUser(_to_user(record), record.password_hash)

    async def get_by_id(self, user_id: uuid.UUID) -> _StoredUser | None:
        record = await self._session.get(UserRecord, user_id)
        return None if record is None else _StoredUser(_to_user(record), record.password_hash)

    async def count(self) -> int:
        result = await self._session.scalar(select(func.count()).select_from(UserRecord))
        return int(result or 0)

    async def list_all(self) -> list[User]:
        records = await self._session.scalars(select(UserRecord).order_by(UserRecord.created_at))
        return [_to_user(record) for record in records]

    async def create(self, *, email: str, password_hash: str, role: Role) -> User:
        record = UserRecord(email=email, password_hash=password_hash, role=role.value)
        self._session.add(record)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictError("a user with this email already exists") from exc
        return _to_user(record)

    async def update_password_hash(self, user_id: uuid.UUID, password_hash: str) -> None:
        await self._session.execute(
            update(UserRecord).where(UserRecord.id == user_id).values(password_hash=password_hash)
        )

    async def delete(self, user_id: uuid.UUID) -> bool:
        result = await self._session.execute(delete(UserRecord).where(UserRecord.id == user_id))
        return bool(affected_rows(result))


@dataclass(frozen=True)
class _TokenState:
    user_id: uuid.UUID
    family_id: uuid.UUID
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None

    @property
    def is_active(self) -> bool:
        return (
            self.used_at is None
            and self.revoked_at is None
            and self.expires_at > datetime.now(tz=UTC)
        )


class PostgresRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        token_hash: str,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        expires_at: datetime,
    ) -> None:
        self._session.add(
            RefreshTokenRecord(
                token_hash=token_hash,
                user_id=user_id,
                family_id=family_id,
                expires_at=expires_at,
            )
        )
        await self._session.flush()

    async def get(self, token_hash: str) -> _TokenState | None:
        record = await self._session.scalar(
            select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == token_hash)
        )
        if record is None:
            return None
        return _TokenState(
            user_id=record.user_id,
            family_id=record.family_id,
            expires_at=record.expires_at,
            used_at=record.used_at,
            revoked_at=record.revoked_at,
        )

    async def mark_used(self, token_hash: str) -> None:
        await self._session.execute(
            update(RefreshTokenRecord)
            .where(RefreshTokenRecord.token_hash == token_hash)
            .values(used_at=datetime.now(tz=UTC))
        )

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        result = await self._session.execute(
            update(RefreshTokenRecord)
            .where(
                RefreshTokenRecord.family_id == family_id,
                RefreshTokenRecord.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(tz=UTC))
        )
        return affected_rows(result)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        result = await self._session.execute(
            update(RefreshTokenRecord)
            .where(
                RefreshTokenRecord.user_id == user_id,
                RefreshTokenRecord.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(tz=UTC))
        )
        return affected_rows(result)
