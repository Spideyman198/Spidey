"""Identity domain model: users, roles, tokens, and abuse-guard policy.

Policy constants live here (not in env config) deliberately: they are security
policy with unit tests, and every additional environment knob is a
misconfiguration surface (docs/14 §1 spirit).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, EmailStr

from spidey.platform.errors import ValidationFailedError

# ── Abuse-guard policy ─────────────────────────────────────────────────────────
# Login attempts per source IP: token bucket, burst 10, sustained 10/minute.
LOGIN_BUCKET_CAPACITY = 10
LOGIN_BUCKET_REFILL_PER_SECOND = 10 / 60
# Consecutive failures per account before a temporary lock (NIST 800-63B §5.2.2).
LOCKOUT_THRESHOLD = 5
LOCKOUT_SECONDS = 900

# NIST 800-63B: length over composition rules; upper bound guards hash-DoS.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


class Role(StrEnum):
    """RBAC roles, strictly ordered: each includes the ones below it."""

    ADMIN = "admin"
    DEVELOPER = "developer"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return {"viewer": 1, "developer": 2, "admin": 3}[self.value]

    def satisfies(self, required: Role) -> bool:
        return self.rank >= required.rank


class User(BaseModel):
    """A platform user. ``password_hash`` never leaves the identity context."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    email: EmailStr
    role: Role
    is_active: bool
    created_at: datetime


class TokenPair(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — scheme name, not a credential
    expires_in: int


class AccessTokenClaims(BaseModel):
    """Validated claims of a decoded access token."""

    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    role: Role
    token_id: str
    expires_at: datetime


def normalize_email(email: str) -> str:
    """Canonical form used for storage, lookup, and lockout keys."""
    return email.strip().lower()


def validate_new_password(password: str, *, email: str) -> None:
    """Password acceptance policy. Raises with a client-safe message."""
    if len(password) < PASSWORD_MIN_LENGTH:
        msg = f"password must be at least {PASSWORD_MIN_LENGTH} characters"
        raise ValidationFailedError(msg)
    if len(password) > PASSWORD_MAX_LENGTH:
        msg = f"password must be at most {PASSWORD_MAX_LENGTH} characters"
        raise ValidationFailedError(msg)
    if normalize_email(email) in password.lower():
        msg = "password must not contain the account email"
        raise ValidationFailedError(msg)
