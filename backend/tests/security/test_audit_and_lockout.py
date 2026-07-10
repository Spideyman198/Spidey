"""Security invariants that need the real database/redis.

- The audit_log is append-only at the database level (trigger), not merely by
  ORM convention.
- Failed-login evidence persists even though the request 'failed'.
- Brute-force lockout engages and blocks even a correct password.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from spidey.identity.domain.models import LOCKOUT_THRESHOLD
from tests.conftest import bootstrap_admin

if TYPE_CHECKING:
    import httpx

pytestmark = pytest.mark.integration


async def _audit_count(client: httpx.AsyncClient, action: str) -> int:
    from sqlalchemy import func, select

    from spidey.platform.audit import AuditLogRecord
    from tests.conftest import app_container

    async with app_container(client).session_factory() as session:
        result = await session.scalar(
            select(func.count()).select_from(AuditLogRecord).where(AuditLogRecord.action == action)
        )
        return int(result or 0)


class TestAppendOnlyAudit:
    async def test_update_and_delete_are_blocked_at_db_level(
        self, app_client: httpx.AsyncClient
    ) -> None:
        from tests.conftest import app_container

        await bootstrap_admin(app_client)  # generates at least one audit row
        async with app_container(app_client).session_factory() as session:
            with pytest.raises(Exception, match="append-only"):
                await session.execute(text("UPDATE audit_log SET outcome = 'tampered'"))
            await session.rollback()
            with pytest.raises(Exception, match="append-only"):
                await session.execute(text("DELETE FROM audit_log"))
            await session.rollback()


class TestFailedLoginEvidence:
    async def test_failed_login_is_audited_despite_request_failure(
        self, app_client: httpx.AsyncClient
    ) -> None:
        await bootstrap_admin(app_client)
        before = await _audit_count(app_client, "auth.login.failed")
        response = await app_client.post(
            "/api/v1/auth/login", json={"email": "admin@spidey.dev", "password": "nope"}
        )
        assert response.status_code == 401
        # The denial rolled back the request, but the evidence was committed.
        assert await _audit_count(app_client, "auth.login.failed") == before + 1


class TestBruteForceLockout:
    async def test_lockout_blocks_correct_password_after_threshold(
        self, app_client: httpx.AsyncClient
    ) -> None:
        await bootstrap_admin(app_client)
        for _ in range(LOCKOUT_THRESHOLD):
            await app_client.post(
                "/api/v1/auth/login", json={"email": "admin@spidey.dev", "password": "wrong"}
            )
        # Correct password now yields 429 (locked), not 200.
        locked = await app_client.post(
            "/api/v1/auth/login", json={"email": "admin@spidey.dev", "password": "AdminPass123!"}
        )
        assert locked.status_code == 429
        assert await _audit_count(app_client, "auth.login.locked_out") >= 1
