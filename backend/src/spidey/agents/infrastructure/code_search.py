"""Native code-search tool — wraps codeintel hybrid search as a ToolSpec.

Security-critical capabilities stay native and are *served* over MCP rather than
replaced by an MCP server (docs/05 §2). The workspace is taken from the trusted
:class:`ToolContext`, never from caller arguments, so a tool call cannot reach
across a workspace boundary. Returned code is wrapped in codeintel's inert data
frame before it can enter a prompt (SEC-PI).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.agents.domain.tools import (
    SideEffect,
    ToolResult,
    ToolSpec,
    TrustTier,
)
from spidey.codeintel.application import GraphExpander, SearchService
from spidey.codeintel.domain import CompressionPolicy, frame_hits
from spidey.codeintel.infrastructure import PostgresGraphStore, PostgresSymbolStore
from spidey.identity.domain.models import Role

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from spidey.agents.domain.tools import ToolContext
    from spidey.codeintel.domain.models import CodeSearchResult
    from spidey.codeintel.domain.ports import (
        DenseEmbedder,
        Reranker,
        SparseEmbedder,
        VectorSearcher,
    )

_TOOL = "codeintel.search"
_MAX_LIMIT = 25
_INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 1, "maxLength": 1024},
        "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT},
    },
    "required": ["query"],
    "additionalProperties": False,
}


class CodeSearchProvider:
    """Native provider offering ``codeintel.search`` over the current workspace."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        dense_embedder: DenseEmbedder,
        sparse_embedder: SparseEmbedder,
        vector_index: VectorSearcher,
        reranker: Reranker | None = None,
        rerank_blend: float = 0.7,
        compression: CompressionPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._dense = dense_embedder
        self._sparse = sparse_embedder
        self._vectors = vector_index
        self._reranker = reranker
        self._rerank_blend = rerank_blend
        self._compression = compression

    @property
    def namespace(self) -> str:
        return "codeintel"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=_TOOL,
                description=(
                    "Hybrid semantic + lexical search over the current workspace's "
                    "code. Returns ranked, attributed code excerpts and related "
                    "knowledge-graph facts."
                ),
                input_schema=_INPUT_SCHEMA,
                side_effect=SideEffect.READ,
                trust_tier=TrustTier.TRUSTED,
                required_role=Role.VIEWER,
            )
        ]

    async def invoke(
        self, name: str, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        if name != _TOOL:
            return ToolResult.error(f"unknown tool {name!r}")
        if context.workspace_id is None:
            return ToolResult.unavailable("no workspace is bound to this run")
        query = arguments.get("query")
        if not isinstance(query, str):
            return ToolResult.error("'query' must be a string")
        raw_limit = arguments.get("limit", 10)
        limit = raw_limit if isinstance(raw_limit, int) else 10

        async with self._session_factory() as session:
            search = SearchService(
                store=PostgresSymbolStore(session),
                dense_embedder=self._dense,
                sparse_embedder=self._sparse,
                vector_index=self._vectors,
                graph_expander=GraphExpander(graph=PostgresGraphStore(session)),
                reranker=self._reranker,
                rerank_blend=self._rerank_blend,
                compression=self._compression,
            )
            result = await search.search(
                workspace_id=context.workspace_id, query=query, limit=limit
            )
        return ToolResult.success(_render(result))


def _render(result: CodeSearchResult) -> str:
    framed = frame_hits(result.hits)
    if result.graph_facts:
        framed += "\n\nRelated (knowledge graph):\n" + "\n".join(
            f"- {fact}" for fact in result.graph_facts
        )
    return framed
