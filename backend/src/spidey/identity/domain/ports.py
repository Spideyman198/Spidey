"""Identity ports. Application services depend on these; adapters implement them.

Contract conventions (docs/14 §8 item 4): docstrings state error semantics;
implementations must not raise adapter-specific exceptions across the port.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from spidey.identity.domain.models import AccessTokenClaims, Role, User
    from spidey.platform.audit import AuditAction


class StoredUser(Protocol):
    """Read model returned by the repository — domain user + secret hash."""

    @property
    def user(self) -> User: ...
    @property
    def password_hash(self) -> str: ...


class UserRepository(Protocol):
    """Persistence for users. Emails are stored normalized and unique."""

    async def get_by_email(self, email: str) -> StoredUser | None: ...
    async def get_by_id(self, user_id: uuid.UUID) -> StoredUser | None: ...
    async def count(self) -> int: ...
    async def list_all(self) -> list[User]: ...

    async def create(self, *, email: str, password_hash: str, role: Role) -> User:
        """Raises ``ConflictError`` when the email already exists."""
        ...

    async def update_password_hash(self, user_id: uuid.UUID, password_hash: str) -> None: ...
    async def delete(self, user_id: uuid.UUID) -> bool:
        """True when a user was deleted; False when it did not exist."""
        ...


class RefreshTokenState(Protocol):
    """State of one stored refresh token (hash-addressed)."""

    @property
    def user_id(self) -> uuid.UUID: ...
    @property
    def family_id(self) -> uuid.UUID: ...
    @property
    def expires_at(self) -> datetime: ...
    @property
    def is_active(self) -> bool:
        """Neither used, revoked, nor expired."""
        ...


class RefreshTokenRepository(Protocol):
    """Rotating refresh-token families. Raw tokens are never stored — only
    SHA-256 hashes; a raw token exists exactly once, in the client's hands."""

    async def create(
        self,
        *,
        token_hash: str,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        expires_at: datetime,
    ) -> None: ...

    async def get(self, token_hash: str) -> RefreshTokenState | None: ...

    async def mark_used(self, token_hash: str) -> None: ...

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        """Revoke every token in a family; returns how many were affected."""
        ...

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int: ...


class SecurityEventSink(Protocol):
    """Persists security-denial evidence and reuse revocation independently of
    the request transaction, so they survive the rollback that accompanies the
    denial. Implementations commit immediately."""

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
    ) -> None: ...

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        """Revoke a refresh-token family on its own committed transaction."""
        ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool:
        """False on mismatch; never raises for wrong passwords."""
        ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class TokenIssuer(Protocol):
    def issue(self, user: User) -> tuple[str, int]:
        """Returns (signed access token, lifetime in seconds)."""
        ...

    def decode(self, token: str) -> AccessTokenClaims:
        """Raises ``UnauthorizedError`` on any signature/claim/expiry problem."""
        ...


class RateLimiter(Protocol):
    async def acquire(self, key: str, *, capacity: int, refill_per_second: float) -> bool:
        """Token-bucket check; True when the request may proceed. Must be
        atomic under concurrency. Unavailability must raise, not allow
        (auth endpoints fail closed)."""
        ...


class LockoutStore(Protocol):
    async def is_locked(self, key: str) -> bool: ...

    async def register_failure(self, key: str, *, threshold: int, lock_seconds: int) -> int:
        """Record a failure; locks the key when the threshold is reached.
        Returns the current consecutive-failure count."""
        ...

    async def reset(self, key: str) -> None: ...
