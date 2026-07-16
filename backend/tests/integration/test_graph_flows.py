"""Knowledge-graph build + recursive-CTE traversals against live Postgres (M5)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.conftest import app_container, bootstrap_admin

if TYPE_CHECKING:
    import httpx

    from spidey.codeintel.domain.models import GraphNeighbor

pytestmark = pytest.mark.integration


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _index_with_graph(client: httpx.AsyncClient, workspace_id: str) -> None:
    from spidey.codeintel.application import IndexService
    from spidey.codeintel.domain.models import ManifestEntry
    from spidey.codeintel.infrastructure import PostgresGraphStore, PostgresSymbolStore
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
        service = IndexService(
            store=PostgresSymbolStore(session),
            parser=container.code_parser,
            graph=PostgresGraphStore(session),
        )
        await service.reindex(workspace_id=wid, manifest=manifest, reader=reader)
        await session.commit()


async def _make_indexed_workspace(client: httpx.AsyncClient, tmp_path: Path, token: str) -> str:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "a.py").write_bytes(
        b"def helper():\n    return 1\n\n\ndef compute(x):\n    return helper() + x\n"
    )
    (source / "b.py").write_bytes(
        b"from a import compute\n\n\n"
        b"class Base:\n    def run(self):\n        return 0\n\n\n"
        b"class Service(Base):\n    def go(self):\n        return compute(1)\n"
    )
    created = await client.post(
        "/api/v1/workspaces",
        headers=_auth(token),
        json={"name": "graph", "source": "local", "location": str(source)},
    )
    wid = created.json()["id"]

    from spidey.platform.audit import AuditLogger
    from spidey.workspaces.application import IngestionService
    from spidey.workspaces.infrastructure import GitPythonProvider, PostgresWorkspaceStore

    container = app_container(client)
    async with container.session_factory() as session:
        await IngestionService(
            store=PostgresWorkspaceStore(session),
            storage=container.workspace_storage,
            git=GitPythonProvider(container.settings),
            cipher=container.cipher,
            audit=AuditLogger(session),
            max_workspace_bytes=container.settings.workspace_max_bytes,
            max_file_bytes=container.settings.ingest_max_file_bytes,
        ).ingest(uuid.UUID(wid))
        await session.commit()

    await _index_with_graph(client, wid)
    return wid


def _names(neighbors: list[GraphNeighbor]) -> set[str]:
    return {n.node.qualified_name for n in neighbors}


class TestGraphTraversals:
    async def test_build_and_traverse(self, app_client: httpx.AsyncClient, tmp_path: Path) -> None:
        from spidey.codeintel.infrastructure import PostgresGraphStore

        token = await bootstrap_admin(app_client)
        wid = uuid.UUID(await _make_indexed_workspace(app_client, tmp_path, token))
        container = app_container(app_client)
        async with container.session_factory() as session:
            graph = PostgresGraphStore(session)

            node_count, edge_count = await graph.counts(wid)
            assert node_count > 0
            assert edge_count > 0

            # callees(compute) — compute calls helper.
            callees = await graph.callees(
                workspace_id=wid, path="a.py", qualified_name="compute", depth=3, limit=50
            )
            assert "helper" in _names(callees)

            # callers(helper) — helper is called by compute (1 hop) and Service.go (2 hops).
            callers = await graph.callers(
                workspace_id=wid, path="a.py", qualified_name="helper", depth=3, limit=50
            )
            assert "compute" in _names(callers)
            assert "Service.go" in _names(callers)

            # impact_set(Base) — Service inherits Base, so it is impacted.
            impact = await graph.impact_set(
                workspace_id=wid, path="b.py", qualified_name="Base", depth=3, limit=50
            )
            assert "Service" in _names(impact)

            # neighborhood(compute) — reaches helper (callee) and Service.go (caller).
            hood = await graph.neighborhood(
                workspace_id=wid, path="a.py", qualified_name="compute", depth=2, limit=50
            )
            assert {"helper", "Service.go"} <= _names(hood)

    async def test_cross_file_call_resolves_by_name(
        self, app_client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        from spidey.codeintel.infrastructure import PostgresGraphStore

        token = await bootstrap_admin(app_client)
        wid = uuid.UUID(await _make_indexed_workspace(app_client, tmp_path, token))
        container = app_container(app_client)
        async with container.session_factory() as session:
            graph = PostgresGraphStore(session)
            # Service.go calls compute, which is defined in a different file.
            callees = await graph.callees(
                workspace_id=wid, path="b.py", qualified_name="Service.go", depth=1, limit=50
            )
            hit = next(n for n in callees if n.node.qualified_name == "compute")
            assert hit.node.path == "a.py"


class TestGraphApi:
    async def test_graph_endpoints_and_facts(
        self, app_client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        token = await bootstrap_admin(app_client)
        # bootstrap_admin already created the admin; reuse its token for the flow.
        wid = await _make_indexed_workspace(app_client, tmp_path, token)

        callers = await app_client.get(
            f"/api/v1/workspaces/{wid}/graph/callers",
            headers=_auth(token),
            params={"symbol": "helper"},
        )
        assert callers.status_code == 200
        body = callers.json()
        qns = {n["node"]["qualified_name"] for n in body["neighbors"]}
        assert "compute" in qns
        # Facts are rendered and directional.
        assert any("helper" in n["fact"] for n in body["neighbors"])

        impact = await app_client.get(
            f"/api/v1/workspaces/{wid}/graph/impact",
            headers=_auth(token),
            params={"symbol": "Base"},
        )
        assert "Service" in {n["node"]["qualified_name"] for n in impact.json()["neighbors"]}

    async def test_unknown_symbol_is_404(
        self, app_client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        token = await bootstrap_admin(app_client)
        wid = await _make_indexed_workspace(app_client, tmp_path, token)
        response = await app_client.get(
            f"/api/v1/workspaces/{wid}/graph/callees",
            headers=_auth(token),
            params={"symbol": "does_not_exist"},
        )
        assert response.status_code == 404

    async def test_search_returns_graph_facts(
        self, app_client: httpx.AsyncClient, tmp_path: Path
    ) -> None:
        token = await bootstrap_admin(app_client)
        wid = await _make_indexed_workspace(app_client, tmp_path, token)
        response = await app_client.get(
            f"/api/v1/workspaces/{wid}/search",
            headers=_auth(token),
            params={"q": "compute the total using a helper", "limit": 5},
        )
        assert response.status_code == 200
        assert "graph_facts" in response.json()
