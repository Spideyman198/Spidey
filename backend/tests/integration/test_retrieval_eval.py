"""Retrieval quality gate: run the golden eval through live hybrid search.

Ingests the committed fixture repo, builds the hybrid index, grades every golden
query with :class:`RetrievalEvalSuite`, and asserts the blessed baselines hold.
Skips when Qdrant is unreachable so the unit-only run stays green.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from spidey.evaluation.application import (
    RetrievalEvalSuite,
    check_baselines,
    load_baselines,
    run_tier,
)
from spidey.evaluation.application.registry import SuiteRegistry
from spidey.evaluation.domain import RetrievalCase, Tier
from tests.conftest import app_container, bootstrap_admin, service_reachable

if TYPE_CHECKING:
    import httpx

pytestmark = pytest.mark.integration

_DATASET = Path(__file__).resolve().parents[3] / "evaluation" / "datasets" / "retrieval"
_BASELINES = Path(__file__).resolve().parents[3] / "evaluation" / "baselines"

_requires_qdrant = pytest.mark.skipif(
    not service_reachable("127.0.0.1", 6333), reason="Qdrant not reachable"
)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _load_golden() -> tuple[list[RetrievalCase], int]:
    spec = json.loads((_DATASET / "golden.json").read_text(encoding="utf-8"))
    cases = [
        RetrievalCase(query=case["query"], relevant=frozenset(case["relevant"]))
        for case in spec["cases"]
    ]
    return cases, int(spec["k"])


async def _ingest_and_index(client: httpx.AsyncClient, token: str) -> str:
    from spidey.codeintel.application import EmbeddingPipeline, IndexService
    from spidey.codeintel.domain.models import ManifestEntry
    from spidey.codeintel.infrastructure import PostgresSymbolStore
    from spidey.platform.audit import AuditLogger
    from spidey.workers.adapters import WorkspaceSourceReader
    from spidey.workspaces.application import IngestionService
    from spidey.workspaces.infrastructure import GitPythonProvider, PostgresWorkspaceStore

    created = await client.post(
        "/api/v1/workspaces",
        headers=_auth(token),
        json={"name": "eval", "source": "local", "location": str(_DATASET / "fixture")},
    )
    wid = uuid.UUID(created.json()["id"])
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
        ).ingest(wid)
        await session.commit()

    async with container.session_factory() as session:
        store = PostgresWorkspaceStore(session)
        stored = await store.get_with_token(workspace_id=wid)
        assert stored is not None
        entries = await store.get_manifest(owner_id=stored.workspace.owner_id, workspace_id=wid)
    manifest = [ManifestEntry(path=e.path, sha256=e.sha256) for e in entries if e.indexable]
    reader = WorkspaceSourceReader(container.workspace_storage.filesystem(wid))
    async with container.session_factory() as session:
        await IndexService(
            store=PostgresSymbolStore(session),
            parser=container.code_parser,
            embedding=EmbeddingPipeline(
                dense=container.dense_embedder,
                sparse=container.sparse_embedder,
                vectors=container.vector_index,
            ),
        ).reindex(workspace_id=wid, manifest=manifest, reader=reader)
        await session.commit()
    return str(wid)


@_requires_qdrant
class TestRetrievalEval:
    async def test_golden_queries_meet_blessed_baselines(
        self, app_client: httpx.AsyncClient
    ) -> None:
        token = await bootstrap_admin(app_client)
        wid = await _ingest_and_index(app_client, token)
        cases, k = _load_golden()

        # Live retriever: each query goes through the real hybrid-search endpoint.
        cache: dict[str, list[str]] = {}
        for case in cases:
            response = await app_client.get(
                f"/api/v1/workspaces/{wid}/search",
                headers=_auth(token),
                params={"q": case.query, "limit": k},
            )
            assert response.status_code == 200
            cache[case.query] = [
                f"{hit['path']}::{hit['header_path']}" for hit in response.json()["hits"]
            ]

        def retriever(query: str, top_k: int) -> list[str]:
            return cache[query][:top_k]

        registry = SuiteRegistry()
        registry.register(RetrievalEvalSuite(cases=cases, retriever=retriever, k=k, tier=Tier.T2))
        report = run_tier(registry, Tier.T2)

        result = report.results[0]
        assert result.passed, f"hard misses: {result.failures}"
        violations = check_baselines(report, load_baselines(_BASELINES))
        assert violations == [], [v.describe() for v in violations]
