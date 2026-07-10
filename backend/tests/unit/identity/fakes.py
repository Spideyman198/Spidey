"""In-memory fakes for identity ports — fast, deterministic, no I/O."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from spidey.identity.domain.models import Role, User

if TYPE_CHECKING:
    from spidey.platform.audit import AuditAction


@dataclass(frozen=True)
class FakeStoredUser:
    user: User
    password_hash: str


class FakeUserRepository:
    def __init__(self) -> None:
        self._by_id: dict[uuid.UUID, FakeStoredUser] = {}

    def seed(self, *, email: str, password_hash: str, role: Role, is_active: bool = True) -> User:
        user = User(
            id=uuid.uuid4(),
            email=email,
            role=role,
            is_active=is_active,
            created_at=datetime.now(tz=UTC),
        )
        self._by_id[user.id] = FakeStoredUser(user, password_hash)
        return user

    async def get_by_email(self, email: str) -> FakeStoredUser | None:
        return next((s for s in self._by_id.values() if s.user.email == email), None)

    async def get_by_id(self, user_id: uuid.UUID) -> FakeStoredUser | None:
        return self._by_id.get(user_id)

    async def count(self) -> int:
        return len(self._by_id)

    async def list_all(self) -> list[User]:
        return [s.user for s in self._by_id.values()]

    async def create(self, *, email: str, password_hash: str, role: Role) -> User:
        from spidey.platform.errors import ConflictError

        if await self.get_by_email(email) is not None:
            raise ConflictError("a user with this email already exists")
        return self.seed(email=email, password_hash=password_hash, role=role)

    async def update_password_hash(self, user_id: uuid.UUID, password_hash: str) -> None:
        stored = self._by_id[user_id]
        self._by_id[user_id] = FakeStoredUser(stored.user, password_hash)

    async def delete(self, user_id: uuid.UUID) -> bool:
        return self._by_id.pop(user_id, None) is not None


@dataclass
class _Token:
    user_id: uuid.UUID
    family_id: uuid.UUID
    expires_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return (
            self.used_at is None
            and self.revoked_at is None
            and self.expires_at > datetime.now(tz=UTC)
        )


class FakeRefreshTokenRepository:
    def __init__(self) -> None:
        self._by_hash: dict[str, _Token] = {}

    async def create(
        self, *, token_hash: str, user_id: uuid.UUID, family_id: uuid.UUID, expires_at: datetime
    ) -> None:
        self._by_hash[token_hash] = _Token(user_id, family_id, expires_at)

    async def get(self, token_hash: str) -> _Token | None:
        return self._by_hash.get(token_hash)

    async def mark_used(self, token_hash: str) -> None:
        self._by_hash[token_hash].used_at = datetime.now(tz=UTC)

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        count = 0
        for token in self._by_hash.values():
            if token.family_id == family_id and token.revoked_at is None:
                token.revoked_at = datetime.now(tz=UTC)
                count += 1
        return count

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        count = 0
        for token in self._by_hash.values():
            if token.user_id == user_id and token.revoked_at is None:
                token.revoked_at = datetime.now(tz=UTC)
                count += 1
        return count


class FakeRateLimiter:
    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[str] = []

    async def acquire(self, key: str, *, capacity: int, refill_per_second: float) -> bool:
        self.calls.append(key)
        return self.allow


class FakeLockoutStore:
    def __init__(self) -> None:
        self.locked: set[str] = set()
        self.failures: dict[str, int] = {}
        self.resets: list[str] = []

    async def is_locked(self, key: str) -> bool:
        return key in self.locked

    async def register_failure(self, key: str, *, threshold: int, lock_seconds: int) -> int:
        self.failures[key] = self.failures.get(key, 0) + 1
        if self.failures[key] >= threshold:
            self.locked.add(key)
        return self.failures[key]

    async def reset(self, key: str) -> None:
        self.resets.append(key)
        self.failures.pop(key, None)
        self.locked.discard(key)


@dataclass
class _AuditEvent:
    action: str
    outcome: str
    details: dict[str, Any]


class FakeAuditLogger:
    def __init__(self) -> None:
        self.events: list[_AuditEvent] = []

    async def record(self, action: AuditAction, *, outcome: str, **details: Any) -> None:
        self.events.append(_AuditEvent(action.value, outcome, details))

    def actions(self) -> list[str]:
        return [e.action for e in self.events]


class FakeSecurityEventSink:
    def __init__(self, refresh_tokens: FakeRefreshTokenRepository) -> None:
        self._refresh_tokens = refresh_tokens
        self.events: list[_AuditEvent] = []

    async def record_denial(self, action: AuditAction, *, outcome: str, **details: Any) -> None:
        self.events.append(_AuditEvent(action.value, outcome, details))

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        return await self._refresh_tokens.revoke_family(family_id)

    def actions(self) -> list[str]:
        return [e.action for e in self.events]


class RealisticHasher:
    """Deterministic hasher good enough for logic tests (not real crypto)."""

    def hash(self, password: str) -> str:
        return f"hashed::{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == f"hashed::{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


class FakeTokenIssuer:
    def __init__(self) -> None:
        self.issued: list[uuid.UUID] = []

    def issue(self, user: User) -> tuple[str, int]:
        self.issued.append(user.id)
        return f"access::{user.id}", 900

    def decode(self, token: str) -> Any:  # unused in service tests
        raise NotImplementedError
