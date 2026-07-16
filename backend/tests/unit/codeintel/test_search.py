"""SearchService: hybrid retrieval with an exact-symbol lexical boost."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from spidey.codeintel.application import GraphExpander, SearchService
from spidey.codeintel.domain.models import (
    EdgeKind,
    GraphNeighbor,
    GraphNode,
    Language,
    Symbol,
    SymbolKind,
)
from spidey.codeintel.domain.ports import VectorMatch
from spidey.platform.vectors import SparseVector

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spidey.platform.vectors import DenseVector

WS = uuid.uuid4()


class FakeDense:
    dimension = 3

    def embed_documents(self, texts: Sequence[str]) -> list[DenseVector]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text: str) -> DenseVector:
        _ = text
        return [0.1, 0.2, 0.3]


class FakeSparse:
    def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        return [SparseVector(indices=[1], values=[1.0]) for _ in texts]

    def embed_query(self, text: str) -> SparseVector:
        _ = text
        return SparseVector(indices=[1], values=[1.0])


class FakeStore:
    """Only the search-relevant slice of SymbolStore is implemented."""

    def __init__(self, names: set[str]) -> None:
        self._names = names
        self.terms_seen: list[str] = []

    async def symbols_for_terms(
        self, *, workspace_id: uuid.UUID, terms: Sequence[str]
    ) -> list[Symbol]:
        self.terms_seen = list(terms)
        return [
            Symbol(
                kind=SymbolKind.FUNCTION,
                name=name,
                qualified_name=f"mod.{name}",
                parent=None,
                start_line=1,
                end_line=2,
                start_byte=0,
                end_byte=1,
            )
            for name in self._names
            if name in {t.lower() for t in terms}
        ]


class FakeVectorIndex:
    def __init__(self, matches: list[VectorMatch]) -> None:
        self._matches = matches
        self.limit_seen: int | None = None

    async def hybrid_search(
        self,
        *,
        workspace_id: uuid.UUID,
        dense: DenseVector,
        sparse: SparseVector,
        limit: int,
    ) -> list[VectorMatch]:
        self.limit_seen = limit
        return self._matches[:limit]


def _match(header_path: str, score: float, *, suspect: bool = False) -> VectorMatch:
    return VectorMatch(
        path="app.py",
        language=Language.PYTHON,
        header_path=header_path,
        kind=SymbolKind.FUNCTION,
        start_line=1,
        end_line=5,
        content=f"def {header_path.rsplit('.', 1)[-1]}(): ...",
        suspect=suspect,
        score=score,
    )


def _service(
    store: FakeStore, index: FakeVectorIndex, *, expander: GraphExpander | None = None
) -> SearchService:
    return SearchService(
        store=store,
        dense_embedder=FakeDense(),
        sparse_embedder=FakeSparse(),
        vector_index=index,
        graph_expander=expander,
    )


class FakeNeighborhood:
    """Returns preset neighbors regardless of seed (satisfies GraphNeighborhood)."""

    def __init__(self, neighbors: list[GraphNeighbor]) -> None:
        self._neighbors = neighbors
        self.seeds_seen: list[str] = []

    async def neighborhood(
        self,
        *,
        workspace_id: uuid.UUID,
        path: str,
        qualified_name: str,
        depth: int,
        limit: int,
    ) -> list[GraphNeighbor]:
        self.seeds_seen.append(qualified_name)
        return self._neighbors


def _neighbor(qn: str) -> GraphNeighbor:
    return GraphNeighbor(
        node=GraphNode(
            path="a.py", qualified_name=qn, name=qn, kind=SymbolKind.FUNCTION, start_line=3
        ),
        edge_kind=EdgeKind.CALLS,
        distance=1,
        via_qualified_name="mod.alpha",
        via_path="a.py",
        line=5,
        outgoing=True,
    )


class TestSearch:
    async def test_empty_query_short_circuits(self) -> None:
        index = FakeVectorIndex([])
        result = await _service(FakeStore(set()), index).search(
            workspace_id=WS, query="   ", limit=5
        )
        assert result.hits == []
        assert result.graph_facts == []
        assert index.limit_seen is None  # never queried the store or index

    async def test_pure_semantic_order_preserved_without_exact_match(self) -> None:
        matches = [_match("mod.alpha", 0.9), _match("mod.beta", 0.5)]
        result = await _service(FakeStore(set()), FakeVectorIndex(matches)).search(
            workspace_id=WS, query="do something vague", limit=10
        )
        assert [h.header_path for h in result.hits] == ["mod.alpha", "mod.beta"]
        assert {h.source for h in result.hits} == {"hybrid"}

    async def test_exact_symbol_hit_is_promoted(self) -> None:
        # 'beta' is a real symbol; even though semantic rank puts it second, an
        # exact identifier query must surface it first and tag it 'symbol'.
        matches = [_match("mod.alpha", 0.9), _match("mod.beta", 0.5)]
        store = FakeStore({"beta"})
        result = await _service(store, FakeVectorIndex(matches)).search(
            workspace_id=WS, query="call beta please", limit=10
        )
        assert result.hits[0].header_path == "mod.beta"
        assert result.hits[0].source == "symbol"
        assert result.hits[1].source == "hybrid"

    async def test_oversamples_then_truncates_to_limit(self) -> None:
        matches = [_match(f"mod.f{i}", 1.0 - i / 100) for i in range(40)]
        index = FakeVectorIndex(matches)
        result = await _service(FakeStore(set()), index).search(
            workspace_id=WS, query="query text", limit=5
        )
        assert index.limit_seen == 5 * 4  # oversample factor
        assert len(result.hits) == 5

    async def test_suspect_flag_flows_through(self) -> None:
        matches = [_match("mod.evil", 0.8, suspect=True)]
        result = await _service(FakeStore(set()), FakeVectorIndex(matches)).search(
            workspace_id=WS, query="anything", limit=5
        )
        assert result.hits[0].suspect is True

    async def test_limit_is_clamped(self) -> None:
        index = FakeVectorIndex([_match("mod.a", 0.5)])
        await _service(FakeStore(set()), index).search(workspace_id=WS, query="q", limit=999)
        assert index.limit_seen == 50 * 4  # clamped to _MAX_LIMIT then oversampled


class TestGraphExpansion:
    async def test_expander_emits_deduped_facts_for_top_seeds(self) -> None:
        matches = [_match("mod.alpha", 0.9), _match("mod.beta", 0.5)]
        neighborhood = FakeNeighborhood([_neighbor("mod.helper"), _neighbor("mod.helper")])
        expander = GraphExpander(graph=neighborhood, hops=1, seeds=1, max_facts=15)
        result = await _service(
            FakeStore(set()), FakeVectorIndex(matches), expander=expander
        ).search(workspace_id=WS, query="anything", limit=10)
        # One fact (deduped), and only the top seed was expanded.
        assert result.graph_facts == ["mod.alpha calls mod.helper (a.py:3)"]
        assert neighborhood.seeds_seen == ["mod.alpha"]

    async def test_no_expander_means_no_facts(self) -> None:
        matches = [_match("mod.alpha", 0.9)]
        result = await _service(FakeStore(set()), FakeVectorIndex(matches)).search(
            workspace_id=WS, query="anything", limit=10
        )
        assert result.graph_facts == []
