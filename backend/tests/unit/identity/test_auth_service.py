"""AuthService logic: login guards, rotation, reuse detection, password change."""

from __future__ import annotations

import pytest

from spidey.identity.application import AuthService
from spidey.identity.domain.models import LOCKOUT_THRESHOLD, Role
from spidey.platform.audit import AuditAction
from spidey.platform.errors import RateLimitedError, UnauthorizedError
from tests.unit.identity.fakes import (
    FakeAuditLogger,
    FakeLockoutStore,
    FakeRateLimiter,
    FakeRefreshTokenRepository,
    FakeSecurityEventSink,
    FakeTokenIssuer,
    FakeUserRepository,
    RealisticHasher,
)

PASSWORD = "CorrectHorseBattery9"


def build_service(
    *,
    rate_limiter: FakeRateLimiter | None = None,
    lockouts: FakeLockoutStore | None = None,
) -> tuple[AuthService, dict[str, object]]:
    users = FakeUserRepository()
    hasher = RealisticHasher()
    refresh_tokens = FakeRefreshTokenRepository()
    audit = FakeAuditLogger()
    security = FakeSecurityEventSink(refresh_tokens)
    user = users.seed(
        email="user@spidey.dev", password_hash=hasher.hash(PASSWORD), role=Role.DEVELOPER
    )
    service = AuthService(
        users=users,
        refresh_tokens=refresh_tokens,
        hasher=hasher,
        issuer=FakeTokenIssuer(),
        rate_limiter=rate_limiter or FakeRateLimiter(),
        lockouts=lockouts or FakeLockoutStore(),
        audit=audit,
        security=security,
        refresh_ttl_days=14,
    )
    return service, {
        "users": users,
        "refresh_tokens": refresh_tokens,
        "audit": audit,
        "security": security,
        "user": user,
    }


async def _login(service: AuthService, password: str = PASSWORD):
    return await service.login(
        "user@spidey.dev", password, source_ip="203.0.113.5", request_id="req-1"
    )


class TestLogin:
    async def test_successful_login_issues_pair_and_audits(self) -> None:
        service, ctx = build_service()
        pair = await _login(service)
        assert pair.access_token
        assert pair.refresh_token
        assert pair.expires_in == 900
        assert AuditAction.LOGIN_SUCCEEDED.value in ctx["audit"].actions()  # type: ignore[attr-defined]

    async def test_wrong_password_is_unauthorized_and_counts_failure(self) -> None:
        service, ctx = build_service()
        with pytest.raises(UnauthorizedError):
            await _login(service, password="wrong")
        # Denial evidence goes to the independent sink, not the request audit.
        assert AuditAction.LOGIN_FAILED.value in ctx["security"].actions()  # type: ignore[attr-defined]

    async def test_unknown_email_is_indistinguishable_from_wrong_password(self) -> None:
        service, _ = build_service()
        with pytest.raises(UnauthorizedError) as exc:
            await service.login("nobody@spidey.dev", PASSWORD, source_ip=None, request_id=None)
        assert exc.value.detail == "invalid email or password"

    async def test_inactive_user_cannot_login(self) -> None:
        service, ctx = build_service()
        users: FakeUserRepository = ctx["users"]  # type: ignore[assignment]
        users.seed(
            email="off@spidey.dev",
            password_hash=RealisticHasher().hash(PASSWORD),
            role=Role.VIEWER,
            is_active=False,
        )
        with pytest.raises(UnauthorizedError):
            await service.login("off@spidey.dev", PASSWORD, source_ip=None, request_id=None)

    async def test_rate_limited_login_is_rejected_before_credential_check(self) -> None:
        service, ctx = build_service(rate_limiter=FakeRateLimiter(allow=False))
        with pytest.raises(RateLimitedError):
            await _login(service)
        assert AuditAction.RATE_LIMITED.value in ctx["security"].actions()  # type: ignore[attr-defined]

    async def test_lockout_after_threshold_failures(self) -> None:
        lockouts = FakeLockoutStore()
        service, _ = build_service(lockouts=lockouts)
        for _ in range(LOCKOUT_THRESHOLD):
            with pytest.raises(UnauthorizedError):
                await _login(service, password="wrong")
        # Now locked: even the correct password is refused.
        with pytest.raises(RateLimitedError):
            await _login(service)

    async def test_successful_login_resets_failure_counter(self) -> None:
        lockouts = FakeLockoutStore()
        service, _ = build_service(lockouts=lockouts)
        with pytest.raises(UnauthorizedError):
            await _login(service, password="wrong")
        await _login(service)
        assert "lock:user@spidey.dev" in lockouts.resets


class TestRefreshRotation:
    async def test_refresh_rotates_and_old_token_is_reuse(self) -> None:
        service, ctx = build_service()
        pair = await _login(service)

        rotated = await service.refresh(pair.refresh_token, source_ip=None, request_id=None)
        assert rotated.refresh_token != pair.refresh_token

        # Reusing the original (now consumed) token is detected.
        with pytest.raises(UnauthorizedError):
            await service.refresh(pair.refresh_token, source_ip=None, request_id=None)
        assert AuditAction.TOKEN_REUSE_DETECTED.value in ctx["security"].actions()  # type: ignore[attr-defined]

    async def test_reuse_burns_the_whole_family(self) -> None:
        service, _ = build_service()
        pair = await _login(service)
        rotated = await service.refresh(pair.refresh_token, source_ip=None, request_id=None)

        with pytest.raises(UnauthorizedError):
            await service.refresh(pair.refresh_token, source_ip=None, request_id=None)
        # The rotated (still-valid) token is now revoked too.
        with pytest.raises(UnauthorizedError):
            await service.refresh(rotated.refresh_token, source_ip=None, request_id=None)

    async def test_unknown_refresh_token_is_unauthorized(self) -> None:
        service, _ = build_service()
        with pytest.raises(UnauthorizedError):
            await service.refresh("not-a-real-token", source_ip=None, request_id=None)


class TestPasswordChange:
    async def test_change_password_revokes_sessions(self) -> None:
        service, ctx = build_service()
        pair = await _login(service)
        user = ctx["user"]

        await service.change_password(
            actor=user,  # type: ignore[arg-type]
            current_password=PASSWORD,
            new_password="BrandNewPassword1",
            source_ip=None,
            request_id=None,
        )
        # Existing refresh token no longer works.
        with pytest.raises(UnauthorizedError):
            await service.refresh(pair.refresh_token, source_ip=None, request_id=None)

    async def test_change_password_requires_correct_current(self) -> None:
        service, ctx = build_service()
        with pytest.raises(UnauthorizedError):
            await service.change_password(
                actor=ctx["user"],  # type: ignore[arg-type]
                current_password="wrong",
                new_password="BrandNewPassword1",
                source_ip=None,
                request_id=None,
            )
