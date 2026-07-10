"""Authentication use cases: login, refresh rotation, logout, password change.

Security invariants implemented here (docs/11, SEC-IAM):
- Enumeration-safe login: unknown email and wrong password are computationally
  and observably identical (dummy hash verification, single error message).
- Fail-closed abuse guards: rate limiter or lockout store unavailability
  aborts authentication rather than skipping the check.
- Refresh rotation with reuse detection: presenting a consumed token revokes
  its entire family and leaves an audit trail.
- Every outcome — success, failure, lockout, reuse — is audited in the same
  transaction as its state change.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from spidey.identity.domain.models import (
    LOCKOUT_SECONDS,
    LOCKOUT_THRESHOLD,
    LOGIN_BUCKET_CAPACITY,
    LOGIN_BUCKET_REFILL_PER_SECOND,
    TokenPair,
    User,
    normalize_email,
    validate_new_password,
)
from spidey.platform.audit import AuditAction
from spidey.platform.errors import RateLimitedError, UnauthorizedError
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from spidey.identity.domain.ports import (
        LockoutStore,
        PasswordHasher,
        RateLimiter,
        RefreshTokenRepository,
        SecurityEventSink,
        TokenIssuer,
        UserRepository,
    )
    from spidey.platform.audit import AuditSink

_logger = get_logger("spidey.identity.auth")

_INVALID_CREDENTIALS = "invalid email or password"
_LOCKED_OUT = "too many failed attempts; try again later"


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        hasher: PasswordHasher,
        issuer: TokenIssuer,
        rate_limiter: RateLimiter,
        lockouts: LockoutStore,
        audit: AuditSink,
        security: SecurityEventSink,
        refresh_ttl_days: int,
    ) -> None:
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._hasher = hasher
        self._issuer = issuer
        self._rate_limiter = rate_limiter
        self._lockouts = lockouts
        # `_audit` writes in the request transaction (success events, atomic
        # with their state change); `_security` commits independently so denial
        # evidence and reuse revocation survive the request rollback.
        self._audit = audit
        self._security = security
        self._refresh_ttl = timedelta(days=refresh_ttl_days)
        # Verified against when the email is unknown, so response timing does
        # not reveal account existence.
        self._enumeration_guard_hash = hasher.hash(secrets.token_urlsafe(16))

    # ── Login ─────────────────────────────────────────────────────────────────

    async def login(
        self,
        email: str,
        password: str,
        *,
        source_ip: str | None,
        request_id: str | None,
    ) -> TokenPair:
        email = normalize_email(email)

        allowed = await self._rate_limiter.acquire(
            f"login:ip:{source_ip or 'unknown'}",
            capacity=LOGIN_BUCKET_CAPACITY,
            refill_per_second=LOGIN_BUCKET_REFILL_PER_SECOND,
        )
        if not allowed:
            await self._security.record_denial(
                AuditAction.RATE_LIMITED,
                outcome="denied",
                target=f"login:{email}",
                source_ip=source_ip,
                request_id=request_id,
            )
            raise RateLimitedError("too many login attempts; slow down")

        if await self._lockouts.is_locked(f"lock:{email}"):
            await self._security.record_denial(
                AuditAction.LOGIN_LOCKED_OUT,
                outcome="denied",
                target=email,
                source_ip=source_ip,
                request_id=request_id,
            )
            raise RateLimitedError(_LOCKED_OUT)

        stored = await self._users.get_by_email(email)
        password_ok = self._hasher.verify(
            stored.password_hash if stored is not None else self._enumeration_guard_hash,
            password,
        )

        if stored is None or not password_ok or not stored.user.is_active:
            failures = await self._lockouts.register_failure(
                f"lock:{email}", threshold=LOCKOUT_THRESHOLD, lock_seconds=LOCKOUT_SECONDS
            )
            await self._security.record_denial(
                AuditAction.LOGIN_FAILED,
                outcome="failure",
                target=email,
                source_ip=source_ip,
                request_id=request_id,
                consecutive_failures=failures,
            )
            raise UnauthorizedError(_INVALID_CREDENTIALS)

        await self._lockouts.reset(f"lock:{email}")
        if self._hasher.needs_rehash(stored.password_hash):
            await self._users.update_password_hash(stored.user.id, self._hasher.hash(password))

        pair = await self._issue_pair(stored.user, family_id=uuid.uuid4())
        await self._audit.record(
            AuditAction.LOGIN_SUCCEEDED,
            outcome="success",
            actor_user_id=stored.user.id,
            source_ip=source_ip,
            request_id=request_id,
        )
        return pair

    # ── Refresh rotation ──────────────────────────────────────────────────────

    async def refresh(
        self,
        raw_refresh_token: str,
        *,
        source_ip: str | None,
        request_id: str | None,
    ) -> TokenPair:
        token_hash = hash_refresh_token(raw_refresh_token)
        state = await self._refresh_tokens.get(token_hash)

        if state is None:
            raise UnauthorizedError("invalid refresh token")

        if not state.is_active:
            # Reuse or revoked-family replay: burn the whole family (OAuth BCP).
            # Both the revocation and its audit commit independently so a
            # detected replay cannot be undone by the request rolling back.
            revoked = await self._security.revoke_family(state.family_id)
            await self._security.record_denial(
                AuditAction.TOKEN_REUSE_DETECTED,
                outcome="denied",
                actor_user_id=state.user_id,
                source_ip=source_ip,
                request_id=request_id,
                family_id=str(state.family_id),
                tokens_revoked=revoked,
            )
            _logger.warning(
                "refresh_token_reuse_detected",
                user_id=str(state.user_id),
                family_id=str(state.family_id),
            )
            raise UnauthorizedError("invalid refresh token")

        stored = await self._users.get_by_id(state.user_id)
        if stored is None or not stored.user.is_active:
            await self._refresh_tokens.revoke_family(state.family_id)
            raise UnauthorizedError("invalid refresh token")

        await self._refresh_tokens.mark_used(token_hash)
        pair = await self._issue_pair(stored.user, family_id=state.family_id)
        await self._audit.record(
            AuditAction.TOKEN_REFRESHED,
            outcome="success",
            actor_user_id=stored.user.id,
            source_ip=source_ip,
            request_id=request_id,
            family_id=str(state.family_id),
        )
        return pair

    # ── Logout ────────────────────────────────────────────────────────────────

    async def logout(
        self,
        raw_refresh_token: str,
        *,
        actor: User,
        source_ip: str | None,
        request_id: str | None,
    ) -> None:
        """Idempotent: revokes the token's family when it belongs to the actor."""
        state = await self._refresh_tokens.get(hash_refresh_token(raw_refresh_token))
        if state is not None and state.user_id == actor.id:
            await self._refresh_tokens.revoke_family(state.family_id)
            await self._audit.record(
                AuditAction.LOGOUT,
                outcome="success",
                actor_user_id=actor.id,
                source_ip=source_ip,
                request_id=request_id,
            )

    # ── Password change ───────────────────────────────────────────────────────

    async def change_password(
        self,
        *,
        actor: User,
        current_password: str,
        new_password: str,
        source_ip: str | None,
        request_id: str | None,
    ) -> None:
        stored = await self._users.get_by_id(actor.id)
        if stored is None or not self._hasher.verify(stored.password_hash, current_password):
            raise UnauthorizedError("current password is incorrect")

        validate_new_password(new_password, email=stored.user.email)
        await self._users.update_password_hash(actor.id, self._hasher.hash(new_password))
        # Every other device/session must re-authenticate.
        revoked = await self._refresh_tokens.revoke_all_for_user(actor.id)
        await self._audit.record(
            AuditAction.PASSWORD_CHANGED,
            outcome="success",
            actor_user_id=actor.id,
            source_ip=source_ip,
            request_id=request_id,
            sessions_revoked=revoked,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _issue_pair(self, user: User, *, family_id: uuid.UUID) -> TokenPair:
        access_token, expires_in = self._issuer.issue(user)
        raw_refresh = secrets.token_urlsafe(48)
        await self._refresh_tokens.create(
            token_hash=hash_refresh_token(raw_refresh),
            user_id=user.id,
            family_id=family_id,
            expires_at=datetime.now(tz=UTC) + self._refresh_ttl,
        )
        return TokenPair(
            access_token=access_token, refresh_token=raw_refresh, expires_in=expires_in
        )
