"""Code-index end-to-end: ingest → index → symbols/status via the API."""

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


async def _run_ingestion(client: httpx.AsyncClient, workspace_id: str) -> None:
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


async def _run_index(client: httpx.AsyncClient, workspace_id: str) -> None:
    from spidey.codeintel.application import IndexService
    from spidey.codeintel.domain.models import ManifestEntry
    from spidey.codeintel.infrastructure import PostgresSymbolStore
    from spidey.workers.adapters import WorkspaceSourceReader
    from spidey.workspaces.infrastructure import PostgresWorkspaceStore

    wid = uuid.UUID(workspace_id)
    container = app_container(client)
    async with container.session_factory() as session:
        stored = await PostgresWorkspaceStore(session).get_with_token(workspace_id=wid)
        assert stored is not None
        entries = await PostgresWorkspaceStore(session).get_manifest(
            owner_id=stored.workspace.owner_id, workspace_id=wid
        )
    manifest = [ManifestEntry(path=e.path, sha256=e.sha256) for e in entries if e.indexable]
    reader = WorkspaceSourceReader(container.workspace_storage.filesystem(wid))
    async with container.session_factory() as session:
        service = IndexService(store=PostgresSymbolStore(session), parser=container.code_parser)
        await service.reindex(workspace_id=wid, manifest=manifest, reader=reader)
        await session.commit()


async def _make_workspace(client: httpx.AsyncClient, token: str, source: Path) -> str:
    created = await client.post(
        "/api/v1/workspaces",
        headers=_auth(token),
        json={"name": "code", "source": "local", "location": str(source)},
    )
    wid = created.json()["id"]
    await _run_ingestion(client, wid)
    return wid


class TestCodeIndex:
    async def test_index_extracts_and_exposes_symbols(
        self, app_client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        source = tmp_path / "repo"
        source.mkdir()
        (source / "app.py").write_bytes(
            b"def handler():\n    return 1\n\nclass Service:\n    def run(self):\n        pass\n"
        )
        (source / "util.go").write_bytes(b"package util\nfunc Helper() {}\n")
        (source / "README.md").write_bytes(b"# docs\n")  # not indexed

        token = await bootstrap_admin(app_client)
        wid = await _make_workspace(app_client, token, source)
        await _run_index(app_client, wid)

        state = await app_client.get(f"/api/v1/workspaces/{wid}/index", headers=_auth(token))
        assert state.status_code == 200
        assert state.json()["status"] == "ready"
        assert state.json()["file_count"] == 2  # app.py, util.go (README skipped)
        assert state.json()["symbol_count"] >= 3

        symbols = await app_client.get(f"/api/v1/workspaces/{wid}/symbols", headers=_auth(token))
        by_qn = {(s["qualified_name"], s["kind"]) for s in symbols.json()}
        assert ("handler", "function") in by_qn
        assert ("Service", "class") in by_qn
        assert ("Service.run", "method") in by_qn
        assert ("Helper", "function") in by_qn

    async def test_symbols_filtered_by_path(
        self, app_client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        source = tmp_path / "repo"
        source.mkdir()
        (source / "a.py").write_bytes(b"def a(): pass\n")
        (source / "b.py").write_bytes(b"def b(): pass\n")

        token = await bootstrap_admin(app_client)
        wid = await _make_workspace(app_client, token, source)
        await _run_index(app_client, wid)

        response = await app_client.get(
            f"/api/v1/workspaces/{wid}/symbols",
            headers=_auth(token),
            params={"path": "a.py"},
        )
        names = {s["name"] for s in response.json()}
        assert names == {"a"}

    async def test_reindex_is_stable(self, app_client: httpx.AsyncClient, tmp_path: Path) -> None:
        source = tmp_path / "repo"
        source.mkdir()
        (source / "a.py").write_bytes(b"def a(): pass\ndef b(): pass\n")

        token = await bootstrap_admin(app_client)
        wid = await _make_workspace(app_client, token, source)
        await _run_index(app_client, wid)
        first = (
            await app_client.get(f"/api/v1/workspaces/{wid}/index", headers=_auth(token))
        ).json()

        # Re-index with an unchanged tree: counts are identical, no duplication.
        await _run_index(app_client, wid)
        second = (
            await app_client.get(f"/api/v1/workspaces/{wid}/index", headers=_auth(token))
        ).json()
        assert first["symbol_count"] == second["symbol_count"]

    async def test_index_ownership_isolation(
        self, app_client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        source = tmp_path / "repo"
        source.mkdir()
        (source / "a.py").write_bytes(b"def a(): pass\n")

        admin = await bootstrap_admin(app_client)
        wid = await _make_workspace(app_client, admin, source)
        await _run_index(app_client, wid)

        from tests.conftest import unique_email

        email = unique_email()
        await app_client.post(
            "/api/v1/users",
            headers=_auth(admin),
            json={"email": email, "password": "DeveloperPass123!", "role": "developer"},
        )
        other = (
            await app_client.post(
                "/api/v1/auth/login", json={"email": email, "password": "DeveloperPass123!"}
            )
        ).json()["access_token"]

        # A non-owner sees a foreign workspace's index as not found.
        assert (
            await app_client.get(f"/api/v1/workspaces/{wid}/symbols", headers=_auth(other))
        ).status_code == 404
        assert (
            await app_client.get(f"/api/v1/workspaces/{wid}/index", headers=_auth(other))
        ).status_code == 404
