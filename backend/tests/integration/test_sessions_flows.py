"""Session and message flows against the live stack: CRUD, ordering, paging."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import bootstrap_admin

if TYPE_CHECKING:
    import httpx

pytestmark = pytest.mark.integration


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestSessionCrud:
    async def test_create_get_rename_delete(self, app_client: httpx.AsyncClient) -> None:
        token = await bootstrap_admin(app_client)
        created = await app_client.post(
            "/api/v1/sessions", headers=_auth(token), json={"title": "first"}
        )
        assert created.status_code == 201
        sid = created.json()["id"]

        got = await app_client.get(f"/api/v1/sessions/{sid}", headers=_auth(token))
        assert got.json()["title"] == "first"

        renamed = await app_client.patch(
            f"/api/v1/sessions/{sid}", headers=_auth(token), json={"title": "renamed"}
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "renamed"

        deleted = await app_client.delete(f"/api/v1/sessions/{sid}", headers=_auth(token))
        assert deleted.status_code == 204
        assert (
            await app_client.get(f"/api/v1/sessions/{sid}", headers=_auth(token))
        ).status_code == 404

    async def test_rename_missing_session_is_404(self, app_client: httpx.AsyncClient) -> None:
        token = await bootstrap_admin(app_client)
        missing = "00000000-0000-0000-0000-000000000000"
        response = await app_client.patch(
            f"/api/v1/sessions/{missing}", headers=_auth(token), json={"title": "x"}
        )
        assert response.status_code == 404


class TestMessages:
    async def test_messages_are_returned_in_chronological_order(
        self, app_client: httpx.AsyncClient
    ) -> None:
        token = await bootstrap_admin(app_client)
        sid = (
            await app_client.post("/api/v1/sessions", headers=_auth(token), json={"title": "chat"})
        ).json()["id"]

        for i in range(5):
            await app_client.post(
                f"/api/v1/sessions/{sid}/messages",
                headers=_auth(token),
                json={"content": f"message {i}"},
            )

        listed = await app_client.get(f"/api/v1/sessions/{sid}/messages", headers=_auth(token))
        contents = [m["content"] for m in listed.json()]
        assert contents == [f"message {i}" for i in range(5)]
        assert all(m["author"] == "user" for m in listed.json())

    async def test_pagination_before_cursor(self, app_client: httpx.AsyncClient) -> None:
        token = await bootstrap_admin(app_client)
        sid = (
            await app_client.post("/api/v1/sessions", headers=_auth(token), json={"title": "chat"})
        ).json()["id"]
        ids: list[str] = []
        for i in range(6):
            resp = await app_client.post(
                f"/api/v1/sessions/{sid}/messages",
                headers=_auth(token),
                json={"content": f"m{i}"},
            )
            ids.append(str(resp.json()["id"]))

        # Page back from the 4th message: expect the earlier ones only.
        page = await app_client.get(
            f"/api/v1/sessions/{sid}/messages",
            headers=_auth(token),
            params={"before": ids[3], "limit": 2},
        )
        contents = [m["content"] for m in page.json()]
        assert contents == ["m1", "m2"]

    async def test_empty_message_rejected(self, app_client: httpx.AsyncClient) -> None:
        token = await bootstrap_admin(app_client)
        sid = (
            await app_client.post("/api/v1/sessions", headers=_auth(token), json={"title": "chat"})
        ).json()["id"]
        response = await app_client.post(
            f"/api/v1/sessions/{sid}/messages", headers=_auth(token), json={"content": ""}
        )
        assert response.status_code == 422
