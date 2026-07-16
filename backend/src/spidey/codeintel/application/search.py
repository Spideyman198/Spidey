"""Hybrid code search (FR-2.3): dense + sparse retrieval with a lexical boost.

The vector index fuses dense (semantic) and sparse (BM25) rankings server-side
via reciprocal-rank fusion. On top of that, an exact identifier in the query
(e.g. a function name) is looked up in the symbol store and the matching hits
are promoted — so a precise name surfaces even when the embedding ranks it low,
while natural-language queries still fall back to pure semantic recall.

Every returned hit carries full provenance and its ``suspect`` screen result;
callers render them through :func:`spidey.codeintel.domain.frame_hits` before any
retrieved text reaches a model (SEC-PI).

When a graph expander is wired (M5), the top hits are expanded one to two hops
through the knowledge graph and the relationships emitted as structured facts
("``Server.__init__`` calls ``parse_config``"), the *useful 20 %* of GraphRAG for
code (docs/06). Expansion is feature-flagged; disabled, search is unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spidey.codeintel.domain.models import CodeSearchResult, SearchHit
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from spidey.codeintel.domain.ports import (
        DenseEmbedder,
        GraphNeighborhood,
        SparseEmbedder,
        SymbolLookup,
        VectorMatch,
        VectorSearcher,
    )

_logger = get_logger("spidey.codeintel.search")

# Identifier-like tokens worth an exact symbol lookup (skip short/common words).
_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
# Pull more candidates than requested so the lexical boost has room to reorder.
_OVERSAMPLE = 4
_MAX_LIMIT = 50


@dataclass(frozen=True, slots=True)
class GraphExpander:
    """Expands top hits into knowledge-graph facts (feature-flagged, M5)."""

    graph: GraphNeighborhood
    hops: int = 1
    seeds: int = 5
    max_facts: int = 15

    async def facts_for(self, workspace_id: uuid.UUID, hits: Sequence[SearchHit]) -> list[str]:
        facts: list[str] = []
        seen: set[str] = set()
        for hit in hits[: self.seeds]:
            neighbors = await self.graph.neighborhood(
                workspace_id=workspace_id,
                path=hit.path,
                qualified_name=hit.header_path,
                depth=self.hops,
                limit=self.max_facts,
            )
            for neighbor in neighbors:
                fact = neighbor.as_fact()
                if fact not in seen:
                    seen.add(fact)
                    facts.append(fact)
                if len(facts) >= self.max_facts:
                    return facts
        return facts


class SearchService:
    def __init__(
        self,
        *,
        store: SymbolLookup,
        dense_embedder: DenseEmbedder,
        sparse_embedder: SparseEmbedder,
        vector_index: VectorSearcher,
        graph_expander: GraphExpander | None = None,
    ) -> None:
        self._store = store
        self._dense = dense_embedder
        self._sparse = sparse_embedder
        self._vectors = vector_index
        self._graph_expander = graph_expander

    async def search(
        self, *, workspace_id: uuid.UUID, query: str, limit: int = 10
    ) -> CodeSearchResult:
        limit = max(1, min(limit, _MAX_LIMIT))
        if not query.strip():
            return CodeSearchResult(hits=[], graph_facts=[])

        exact_names = await self._exact_symbol_names(workspace_id, query)

        dense = self._dense.embed_query(query)
        sparse = self._sparse.embed_query(query)
        matches = await self._vectors.hybrid_search(
            workspace_id=workspace_id,
            dense=dense,
            sparse=sparse,
            limit=limit * _OVERSAMPLE,
        )

        hits = [self._to_hit(match, exact_names) for match in matches]
        # Stable sort: promote exact-symbol hits, preserve RRF order within each
        # group (Python sort is stable, so equal keys keep candidate order).
        hits.sort(key=lambda h: h.source != "symbol")
        hits = hits[:limit]

        facts: list[str] = []
        if self._graph_expander is not None and hits:
            facts = await self._graph_expander.facts_for(workspace_id, hits)
        return CodeSearchResult(hits=hits, graph_facts=facts)

    async def _exact_symbol_names(self, workspace_id: uuid.UUID, query: str) -> set[str]:
        terms = set(_TERM_RE.findall(query))
        if not terms:
            return set()
        symbols = await self._store.symbols_for_terms(workspace_id=workspace_id, terms=list(terms))
        return {s.name.lower() for s in symbols}

    @staticmethod
    def _to_hit(match: VectorMatch, exact_names: set[str]) -> SearchHit:
        leaf = match.header_path.rsplit(".", 1)[-1].lower()
        is_exact = leaf in exact_names
        return SearchHit(
            path=match.path,
            language=match.language,
            header_path=match.header_path,
            kind=match.kind,
            start_line=match.start_line,
            end_line=match.end_line,
            content=match.content,
            score=match.score,
            suspect=match.suspect,
            source="symbol" if is_exact else "hybrid",
        )
