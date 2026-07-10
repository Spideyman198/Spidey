"""Workspace API + end-to-end ingestion against the live stack."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.conftest import app_container, bootstrap_admin

if TYPE_CHECKING:
    import httpx

pytestmark = pytest.mark.integration


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _developer_token(client: httpx.AsyncClient, admin: str) -> str:
    from tests.conftest import unique_email

    email = unique_email()
    await client.post(
        "/api/v1/users",
        headers=_auth(admin),
        json={"email": email, "password": "DeveloperPass123!", "role": "developer"},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "DeveloperPass123!"}
    )
    return login.json()["access_token"]


class TestWorkspaceApi:
    async def test_create_returns_pending_and_hides_token(
        self, app_client: httpx.AsyncClient
    ) -> None:
        token = await bootstrap_admin(app_client)
        response = await app_client.post(
            "/api/v1/workspaces",
            headers=_auth(token),
            json={
                "name": "demo",
                "source": "github",
                "location": "https://github.com/o/r.git",
                "branch": "main",
                "token": "ghp_supersecret",
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pending"
        # The PAT must never appear anywhere in the response.
        assert "ghp_supersecret" not in response.text
        assert "token" not in body

    async def test_viewer_cannot_create(self, app_client: httpx.AsyncClient) -> None:
        admin = await bootstrap_admin(app_client)
        from tests.conftest import unique_email

        email = unique_email()
        await app_client.post(
            "/api/v1/users",
            headers=_auth(admin),
            json={"email": email, "password": "ViewerPass12345!", "role": "viewer"},
        )
        viewer = (
            await app_client.post(
                "/api/v1/auth/login", json={"email": email, "password": "ViewerPass12345!"}
            )
        ).json()["access_token"]

        response = await app_client.post(
            "/api/v1/workspaces",
            headers=_auth(viewer),
            json={"name": "x", "source": "github", "location": "https://github.com/o/r.git"},
        )
        assert response.status_code == 403

    async def test_ownership_isolation(self, app_client: httpx.AsyncClient) -> None:
        admin = await bootstrap_admin(app_client)
        alice = await _developer_token(app_client, admin)
        bob = await _developer_token(app_client, admin)

        created = await app_client.post(
            "/api/v1/workspaces",
            headers=_auth(alice),
            json={"name": "a", "source": "github", "location": "https://github.com/o/r.git"},
        )
        workspace_id = created.json()["id"]

        # Bob gets 404 (not 403): existence is not disclosed across owners.
        assert (
            await app_client.get(f"/api/v1/workspaces/{workspace_id}", headers=_auth(bob))
        ).status_code == 404
        assert len((await app_client.get("/api/v1/workspaces", headers=_auth(bob))).json()) == 0


class TestEndToEndIngestion:
    async def test_local_ingestion_persists_manifest(
        self, app_client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        # A local source tree the app process can read.
        source = tmp_path / "repo"
        source.mkdir()
        (source / "main.py").write_bytes(b"print('hello')\n")
        (source / "notes.md").write_bytes(b"# notes\n")
        (source / ".gitignore").write_bytes(b"*.log\n")
        (source / "debug.log").write_bytes(b"ignored\n")

        token = await bootstrap_admin(app_client)
        created = await app_client.post(
            "/api/v1/workspaces",
            headers=_auth(token),
            json={"name": "local", "source": "local", "location": str(source)},
        )
        workspace_id = created.json()["id"]

        # Run ingestion directly against the live DB (no Celery worker in-process).
        await _run_ingestion(app_client, workspace_id)

        detail = await app_client.get(f"/api/v1/workspaces/{workspace_id}", headers=_auth(token))
        assert detail.json()["status"] == "ready"
        assert detail.json()["file_count"] == 3  # main.py, notes.md, .gitignore

        files = await app_client.get(
            f"/api/v1/workspaces/{workspace_id}/files", headers=_auth(token)
        )
        paths = {e["path"] for e in files.json()}
        assert paths == {"main.py", "notes.md", ".gitignore"}
        assert "debug.log" not in paths  # gitignored

    async def test_delete_removes_workspace_and_tree(
        self, app_client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        source = tmp_path / "repo"
        source.mkdir()
        (source / "f.py").write_bytes(b"x = 1\n")

        token = await bootstrap_admin(app_client)
        created = await app_client.post(
            "/api/v1/workspaces",
            headers=_auth(token),
            json={"name": "local", "source": "local", "location": str(source)},
        )
        workspace_id = created.json()["id"]
        await _run_ingestion(app_client, workspace_id)

        storage = app_container(app_client).workspace_storage
        root = Path(storage.path_for(uuid.UUID(workspace_id)))
        assert root.exists()

        deleted = await app_client.delete(
            f"/api/v1/workspaces/{workspace_id}", headers=_auth(token)
        )
        assert deleted.status_code == 204
        assert not root.exists()
        assert (
            await app_client.get(f"/api/v1/workspaces/{workspace_id}", headers=_auth(token))
        ).status_code == 404


async def _run_ingestion(client: httpx.AsyncClient, workspace_id: str) -> None:
    import uuid

    from spidey.platform.audit import AuditLogger
    from spidey.workspaces.application import IngestionService
    from spidey.workspaces.infrastructure import (
        GitPythonProvider,
        PostgresWorkspaceStore,
    )

    container = app_container(client)
    async with container.session_factory() as session:
        service = IngestionService(
            store=PostgresWorkspaceStore(session),
            storage=container.workspace_storage,
            git=GitPythonProvider(container.settings),
            cipher=container.cipher,
            audit=AuditLogger(session),
            max_workspace_bytes=container.settings.workspace_max_bytes,
            max_file_bytes=container.settings.ingest_max_file_bytes,
        )
        await service.ingest(uuid.UUID(workspace_id))
        await session.commit()
