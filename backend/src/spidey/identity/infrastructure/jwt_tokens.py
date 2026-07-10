"""HS256 access tokens via PyJWT.

Symmetric signing is deliberate: one monolith signs and verifies (ADR-0001);
asymmetric keys pay rotation and key-management cost for a consumer that
doesn't exist. ``iss``/``aud`` are pinned so a token minted by anything else —
or for another audience — never validates.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import jwt

from spidey.identity.domain.models import AccessTokenClaims, Role
from spidey.platform.errors import UnauthorizedError

if TYPE_CHECKING:
    from spidey.identity.domain.models import User

_ALGORITHM = "HS256"
_ISSUER = "spidey"
_AUDIENCE = "spidey-api"


class JwtTokenIssuer:
    def __init__(self, *, secret: str, ttl_seconds: int) -> None:
        self._secret = secret
        self._ttl_seconds = ttl_seconds

    def issue(self, user: User) -> tuple[str, int]:
        now = datetime.now(tz=UTC)
        payload: dict[str, Any] = {
            "sub": str(user.id),
            "role": user.role.value,
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + timedelta(seconds=self._ttl_seconds),
            "iss": _ISSUER,
            "aud": _AUDIENCE,
        }
        return jwt.encode(payload, self._secret, algorithm=_ALGORITHM), self._ttl_seconds

    def decode(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[_ALGORITHM],
                issuer=_ISSUER,
                audience=_AUDIENCE,
                options={"require": ["sub", "role", "jti", "exp", "iat", "iss", "aud"]},
            )
            return AccessTokenClaims(
                user_id=uuid.UUID(payload["sub"]),
                role=Role(payload["role"]),
                token_id=str(payload["jti"]),
                expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
            )
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise UnauthorizedError("invalid or expired token") from exc
