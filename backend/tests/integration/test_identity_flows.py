"""End-to-end identity flows against the live stack."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.integration.conftest import bootstrap_admin, unique_email

if TYPE_CHECKING:
    import httpx

pytestmark = pytest.mark.integration


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestAuthFlow:
    async def test_login_me_and_role(self, app_client: httpx.AsyncClient) -> None:
        token = await bootstrap_admin(app_client)
        response = await app_client.get("/api/v1/users/me", headers=_auth(token))
        assert response.status_code == 200
        assert response.json()["role"] == "admin"

    async def test_protected_route_requires_token(self, app_client: httpx.AsyncClient) -> None:
        assert (await app_client.get("/api/v1/users/me")).status_code == 401

    async def test_wrong_password_rejected(self, app_client: httpx.AsyncClient) -> None:
        await bootstrap_admin(app_client)
        response = await app_client.post(
            "/api/v1/auth/login", json={"email": "admin@spidey.dev", "password": "wrong"}
        )
        assert response.status_code == 401

    async def test_refresh_rotation_and_reuse_detection(
        self, app_client: httpx.AsyncClient
    ) -> None:
        await bootstrap_admin(app_client)
        login = await app_client.post(
            "/api/v1/auth/login", json={"email": "admin@spidey.dev", "password": "AdminPass123!"}
        )
        original = login.json()["refresh_token"]

        rotated = await app_client.post("/api/v1/auth/refresh", json={"refresh_token": original})
        assert rotated.status_code == 200
        new_token = rotated.json()["refresh_token"]
        assert new_token != original

        # Reuse of the consumed token is rejected and burns the family.
        reuse = await app_client.post("/api/v1/auth/refresh", json={"refresh_token": original})
        assert reuse.status_code == 401
        after = await app_client.post("/api/v1/auth/refresh", json={"refresh_token": new_token})
        assert after.status_code == 401

    async def test_change_password_revokes_and_reauth_works(
        self, app_client: httpx.AsyncClient
    ) -> None:
        token = await bootstrap_admin(app_client)
        login = await app_client.post(
            "/api/v1/auth/login", json={"email": "admin@spidey.dev", "password": "AdminPass123!"}
        )
        refresh = login.json()["refresh_token"]

        changed = await app_client.post(
            "/api/v1/auth/change-password",
            headers=_auth(token),
            json={"current_password": "AdminPass123!", "new_password": "EvenBetterPass456!"},
        )
        assert changed.status_code == 204
        # Old refresh token is dead.
        assert (
            await app_client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        ).status_code == 401
        # New password works.
        assert (
            await app_client.post(
                "/api/v1/auth/login",
                json={"email": "admin@spidey.dev", "password": "EvenBetterPass456!"},
            )
        ).status_code == 200


class TestUserAdministration:
    async def test_admin_creates_and_lists_users(self, app_client: httpx.AsyncClient) -> None:
        token = await bootstrap_admin(app_client)
        email = unique_email()
        created = await app_client.post(
            "/api/v1/users",
            headers=_auth(token),
            json={"email": email, "password": "DeveloperPass123!", "role": "developer"},
        )
        assert created.status_code == 201
        listing = await app_client.get("/api/v1/users", headers=_auth(token))
        assert email in {u["email"] for u in listing.json()}

    async def test_duplicate_email_conflict(self, app_client: httpx.AsyncClient) -> None:
        token = await bootstrap_admin(app_client)
        email = unique_email()
        body = {"email": email, "password": "DeveloperPass123!", "role": "developer"}
        assert (
            await app_client.post("/api/v1/users", headers=_auth(token), json=body)
        ).status_code == 201
        assert (
            await app_client.post("/api/v1/users", headers=_auth(token), json=body)
        ).status_code == 409

    async def test_admin_cannot_delete_self(self, app_client: httpx.AsyncClient) -> None:
        token = await bootstrap_admin(app_client)
        me = (await app_client.get("/api/v1/users/me", headers=_auth(token))).json()
        response = await app_client.delete(f"/api/v1/users/{me['id']}", headers=_auth(token))
        assert response.status_code == 403
