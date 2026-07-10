"""Identity domain: RBAC ordering, password policy, token adapters."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from spidey.identity.domain.models import Role, User, normalize_email, validate_new_password
from spidey.identity.infrastructure import Argon2PasswordHasher, JwtTokenIssuer
from spidey.platform.errors import UnauthorizedError, ValidationFailedError


class TestRoleOrdering:
    def test_admin_satisfies_all(self) -> None:
        assert Role.ADMIN.satisfies(Role.ADMIN)
        assert Role.ADMIN.satisfies(Role.DEVELOPER)
        assert Role.ADMIN.satisfies(Role.VIEWER)

    def test_viewer_satisfies_only_viewer(self) -> None:
        assert Role.VIEWER.satisfies(Role.VIEWER)
        assert not Role.VIEWER.satisfies(Role.DEVELOPER)
        assert not Role.VIEWER.satisfies(Role.ADMIN)

    def test_developer_middle(self) -> None:
        assert Role.DEVELOPER.satisfies(Role.VIEWER)
        assert not Role.DEVELOPER.satisfies(Role.ADMIN)


class TestPasswordPolicy:
    def test_minimum_length(self) -> None:
        with pytest.raises(ValidationFailedError, match="at least"):
            validate_new_password("short1", email="a@b.dev")

    def test_maximum_length(self) -> None:
        with pytest.raises(ValidationFailedError, match="at most"):
            validate_new_password("a" * 200, email="a@b.dev")

    def test_rejects_password_containing_email(self) -> None:
        with pytest.raises(ValidationFailedError, match="email"):
            validate_new_password("alice@b.dev-supersecret", email="alice@b.dev")

    def test_accepts_reasonable_password(self) -> None:
        validate_new_password("a-perfectly-fine-passphrase", email="a@b.dev")

    def test_email_normalization(self) -> None:
        assert normalize_email("  Alice@Example.DEV ") == "alice@example.dev"


class TestArgon2Hasher:
    def test_hash_verify_roundtrip(self) -> None:
        hasher = Argon2PasswordHasher()
        h = hasher.hash("s3cret-passphrase")
        assert h != "s3cret-passphrase"
        assert hasher.verify(h, "s3cret-passphrase")

    def test_wrong_password_returns_false_not_raise(self) -> None:
        hasher = Argon2PasswordHasher()
        assert hasher.verify(hasher.hash("right"), "wrong") is False

    def test_malformed_hash_is_false(self) -> None:
        assert Argon2PasswordHasher().verify("not-a-hash", "whatever") is False


class TestJwtIssuer:
    def _user(self, role: Role = Role.DEVELOPER) -> User:
        return User(
            id=uuid.uuid4(),
            email="u@spidey.dev",
            role=role,
            is_active=True,
            created_at=datetime.now(tz=UTC),
        )

    def test_issue_and_decode_roundtrip(self) -> None:
        issuer = JwtTokenIssuer(secret="x" * 40, ttl_seconds=900)
        user = self._user(Role.ADMIN)
        token, ttl = issuer.issue(user)
        assert ttl == 900
        claims = issuer.decode(token)
        assert claims.user_id == user.id
        assert claims.role is Role.ADMIN

    def test_tampered_token_rejected(self) -> None:
        issuer = JwtTokenIssuer(secret="x" * 40, ttl_seconds=900)
        token, _ = issuer.issue(self._user())
        with pytest.raises(UnauthorizedError):
            issuer.decode(token + "tamper")

    def test_wrong_secret_rejected(self) -> None:
        token, _ = JwtTokenIssuer(secret="a" * 40, ttl_seconds=900).issue(self._user())
        with pytest.raises(UnauthorizedError):
            JwtTokenIssuer(secret="b" * 40, ttl_seconds=900).decode(token)

    def test_expired_token_rejected(self) -> None:
        issuer = JwtTokenIssuer(secret="x" * 40, ttl_seconds=-1)
        token, _ = issuer.issue(self._user())
        with pytest.raises(UnauthorizedError):
            issuer.decode(token)

    def test_garbage_is_rejected(self) -> None:
        with pytest.raises(UnauthorizedError):
            JwtTokenIssuer(secret="x" * 40, ttl_seconds=900).decode("not.a.jwt")
