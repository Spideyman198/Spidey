"""QdrantVectorIndex contract via a fake client — collection lifecycle, guards,
payload round-trip — without a live server."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from qdrant_client import models

from spidey.codeintel.domain.models import Language, SymbolKind
from spidey.codeintel.domain.ports import VectorRecord
from spidey.codeintel.infrastructure import QdrantVectorIndex
from spidey.platform.vectors import SparseVector

if TYPE_CHECKING:
    from collections.abc import Sequence

WS = uuid.uuid4()


class _QueryResult:
    """Minimal stand-in for the query response — the adapter reads ``.points``."""

    def __init__(self, points: list[models.ScoredPoint]) -> None:
        self.points = points


class FakeClient:
    """Records calls; ``existing`` seeds which collections already exist."""

    def __init__(self, *, existing: set[str] | None = None) -> None:
        self.collections = set(existing or set())
        self.created: list[str] = []
        self.payload_indexed: list[str] = []
        self.upserted: dict[str, list[models.PointStruct]] = {}
        self.deleted: list[Any] = []
        self.dropped: list[str] = []
        self.queried: list[str] = []
        self.response_points: list[models.ScoredPoint] = []

    async def collection_exists(self, name: str) -> bool:
        return name in self.collections

    async def create_collection(self, *, collection_name: str, **_: Any) -> None:
        self.collections.add(collection_name)
        self.created.append(collection_name)

    async def create_payload_index(self, *, collection_name: str, **_: Any) -> None:
        self.payload_indexed.append(collection_name)

    async def upsert(self, *, collection_name: str, points: Sequence[models.PointStruct]) -> None:
        self.upserted.setdefault(collection_name, []).extend(points)

    async def delete(self, *, collection_name: str, points_selector: Any) -> None:
        self.deleted.append((collection_name, points_selector))

    async def query_points(self, *, collection_name: str, **_: Any) -> _QueryResult:
        self.queried.append(collection_name)
        return _QueryResult(self.response_points)

    async def delete_collection(self, name: str) -> None:
        self.collections.discard(name)
        self.dropped.append(name)


def _index(client: FakeClient) -> QdrantVectorIndex:
    return QdrantVectorIndex(client=client, collection_prefix="code", dense_dim=3)  # type: ignore[arg-type]


def _record() -> VectorRecord:
    return VectorRecord(
        point_id=uuid.uuid5(uuid.NAMESPACE_URL, "x"),
        dense=[0.1, 0.2, 0.3],
        sparse=SparseVector(indices=[1], values=[2.0]),
        path="a.py",
        language=Language.PYTHON,
        header_path="mod.f",
        kind=SymbolKind.FUNCTION,
        start_line=1,
        end_line=4,
        content="def f(): ...",
        suspect=False,
    )


class TestEnsureCollection:
    async def test_creates_with_payload_index_when_absent(self) -> None:
        client = FakeClient()
        await _index(client).ensure_collection(WS)
        name = f"code_{WS.hex}"
        assert client.created == [name]
        assert client.payload_indexed == [name]

    async def test_noop_when_already_exists(self) -> None:
        name = f"code_{WS.hex}"
        client = FakeClient(existing={name})
        await _index(client).ensure_collection(WS)
        assert client.created == []


class TestWriteGuards:
    async def test_empty_upsert_is_noop(self) -> None:
        client = FakeClient(existing={f"code_{WS.hex}"})
        await _index(client).upsert(workspace_id=WS, records=[])
        assert client.upserted == {}

    async def test_upsert_maps_payload_and_named_vectors(self) -> None:
        name = f"code_{WS.hex}"
        client = FakeClient(existing={name})
        await _index(client).upsert(workspace_id=WS, records=[_record()])
        point = client.upserted[name][0]
        assert set(point.vector) == {"dense", "bm25"}  # type: ignore[arg-type]
        assert point.payload is not None
        assert point.payload["header_path"] == "mod.f"
        assert point.payload["suspect"] is False

    async def test_delete_by_paths_empty_is_noop(self) -> None:
        client = FakeClient(existing={f"code_{WS.hex}"})
        await _index(client).delete_by_paths(workspace_id=WS, paths=[])
        assert client.deleted == []

    async def test_delete_by_paths_skips_missing_collection(self) -> None:
        client = FakeClient()  # collection absent
        await _index(client).delete_by_paths(workspace_id=WS, paths=["a.py"])
        assert client.deleted == []

    async def test_delete_by_paths_filters_on_path(self) -> None:
        client = FakeClient(existing={f"code_{WS.hex}"})
        await _index(client).delete_by_paths(workspace_id=WS, paths=["a.py", "b.py"])
        assert len(client.deleted) == 1


class TestSearch:
    async def test_missing_collection_returns_empty(self) -> None:
        client = FakeClient()  # never indexed
        hits = await _index(client).hybrid_search(
            workspace_id=WS,
            dense=[0.1, 0.2, 0.3],
            sparse=SparseVector(indices=[1], values=[1.0]),
            limit=5,
        )
        assert hits == []
        assert client.queried == []

    async def test_maps_scored_points_to_matches(self) -> None:
        name = f"code_{WS.hex}"
        client = FakeClient(existing={name})
        client.response_points = [
            models.ScoredPoint(
                id="p1",
                version=0,
                score=0.42,
                payload={
                    "path": "a.py",
                    "language": "python",
                    "header_path": "mod.f",
                    "kind": "function",
                    "start_line": 1,
                    "end_line": 4,
                    "content": "def f(): ...",
                    "suspect": True,
                },
            )
        ]
        hits = await _index(client).hybrid_search(
            workspace_id=WS,
            dense=[0.1, 0.2, 0.3],
            sparse=SparseVector(indices=[1], values=[1.0]),
            limit=5,
        )
        assert len(hits) == 1
        assert hits[0].header_path == "mod.f"
        assert hits[0].kind is SymbolKind.FUNCTION
        assert hits[0].suspect is True
        assert hits[0].score == 0.42


class TestDrop:
    async def test_drop_deletes_existing_collection(self) -> None:
        name = f"code_{WS.hex}"
        client = FakeClient(existing={name})
        await _index(client).drop(WS)
        assert client.dropped == [name]

    async def test_drop_noop_when_absent(self) -> None:
        client = FakeClient()
        await _index(client).drop(WS)
        assert client.dropped == []
