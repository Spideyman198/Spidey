"""Authorization matrix and ownership isolation (SEC-IAM, SEC-WEB).

Attack-shaped: asserts that roles below the requirement are refused and that
one user can never reach another's resources — including that a foreign
resource is indistinguishable from a missing one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.integration.conftest import bootstrap_admin, unique_email

if TYPE_CHECKING:
    import httpx

pytestmark = pytest.mark.integration


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_user(client: httpx.AsyncClient, admin_token: str, role: str) -> tuple[str, str]:
    email = unique_email()
    await client.post(
        "/api/v1/users",
        headers=_auth(admin_token),
        json={"email": email, "password": "MemberPass123!", "role": role},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "MemberPass123!"}
    )
    return email, login.json()["access_token"]


class TestRoleMatrix:
    async def test_admin_only_routes_reject_lower_roles(
        self, app_client: httpx.AsyncClient
    ) -> None:
        admin = await bootstrap_admin(app_client)
        _, dev = await _make_user(app_client, admin, "developer")
        _, viewer = await _make_user(app_client, admin, "viewer")

        # Admin-only: create user, list users, delete user.
        for token in (dev, viewer):
            assert (await app_client.get("/api/v1/users", headers=_auth(token))).status_code == 403
            assert (
                await app_client.post(
                    "/api/v1/users",
                    headers=_auth(token),
                    json={"email": unique_email(), "password": "x-Passw0rd-yz", "role": "viewer"},
                )
            ).status_code == 403

        # Admin itself is allowed.
        assert (await app_client.get("/api/v1/users", headers=_auth(admin))).status_code == 200

    async def test_all_roles_can_use_their_own_sessions(
        self, app_client: httpx.AsyncClient
    ) -> None:
        admin = await bootstrap_admin(app_client)
        for role in ("developer", "viewer"):
            _, token = await _make_user(app_client, admin, role)
            created = await app_client.post(
                "/api/v1/sessions", headers=_auth(token), json={"title": "hi"}
            )
            assert created.status_code == 201

    async def test_missing_token_and_garbage_token_rejected(
        self, app_client: httpx.AsyncClient
    ) -> None:
        assert (await app_client.get("/api/v1/sessions")).status_code == 401
        assert (
            await app_client.get("/api/v1/sessions", headers=_auth("garbage.token.value"))
        ).status_code == 401


class TestOwnershipIsolation:
    async def test_foreign_session_is_not_found_not_forbidden(
        self, app_client: httpx.AsyncClient
    ) -> None:
        admin = await bootstrap_admin(app_client)
        _, alice = await _make_user(app_client, admin, "developer")
        _, bob = await _make_user(app_client, admin, "developer")

        session = await app_client.post(
            "/api/v1/sessions", headers=_auth(alice), json={"title": "alice private"}
        )
        session_id = session.json()["id"]

        # Bob — and even the admin — get 404, not 403: existence is not disclosed.
        for token in (bob, admin):
            got = await app_client.get(f"/api/v1/sessions/{session_id}", headers=_auth(token))
            assert got.status_code == 404
            deleted = await app_client.delete(
                f"/api/v1/sessions/{session_id}", headers=_auth(token)
            )
            assert deleted.status_code == 404

    async def test_cannot_post_message_to_foreign_session(
        self, app_client: httpx.AsyncClient
    ) -> None:
        admin = await bootstrap_admin(app_client)
        _, alice = await _make_user(app_client, admin, "developer")
        _, bob = await _make_user(app_client, admin, "developer")

        session = await app_client.post(
            "/api/v1/sessions", headers=_auth(alice), json={"title": "alice"}
        )
        session_id = session.json()["id"]
        response = await app_client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=_auth(bob),
            json={"content": "sneaking in"},
        )
        assert response.status_code == 404

    async def test_session_list_shows_only_own(self, app_client: httpx.AsyncClient) -> None:
        admin = await bootstrap_admin(app_client)
        _, alice = await _make_user(app_client, admin, "developer")
        _, bob = await _make_user(app_client, admin, "developer")

        await app_client.post("/api/v1/sessions", headers=_auth(alice), json={"title": "a"})
        await app_client.post("/api/v1/sessions", headers=_auth(bob), json={"title": "b1"})
        await app_client.post("/api/v1/sessions", headers=_auth(bob), json={"title": "b2"})

        alice_list = (await app_client.get("/api/v1/sessions", headers=_auth(alice))).json()
        bob_list = (await app_client.get("/api/v1/sessions", headers=_auth(bob))).json()
        assert len(alice_list) == 1
        assert len(bob_list) == 2
