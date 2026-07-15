"""Qdrant adapter for the per-workspace hybrid vector index (M4).

Each workspace gets its own collection carrying two named vectors — ``dense``
(cosine over the semantic embedding) and ``bm25`` (a sparse vector with the
server-side IDF modifier). A query prefetches both and fuses their rankings with
reciprocal-rank fusion, so lexical and semantic signals combine without the
client ever seeing raw distances. Per-workspace collections make cross-tenant
retrieval structurally impossible.

The chunk text lives in the point payload, so a search returns everything a hit
needs (content + provenance) with no filesystem read on the query path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qdrant_client import AsyncQdrantClient, models

from spidey.codeintel.domain.models import Language, SymbolKind
from spidey.codeintel.domain.ports import VectorMatch
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from spidey.codeintel.domain.ports import VectorRecord
    from spidey.platform.vectors import DenseVector, SparseVector

_DENSE = "dense"
_SPARSE = "bm25"
_logger = get_logger("spidey.codeintel.qdrant")


class QdrantVectorIndex:
    def __init__(
        self,
        *,
        client: AsyncQdrantClient,
        collection_prefix: str,
        dense_dim: int,
    ) -> None:
        self._client = client
        self._prefix = collection_prefix
        self._dim = dense_dim

    def _collection(self, workspace_id: uuid.UUID) -> str:
        return f"{self._prefix}_{workspace_id.hex}"

    async def ensure_collection(self, workspace_id: uuid.UUID) -> None:
        name = self._collection(workspace_id)
        if await self._client.collection_exists(name):
            return
        await self._client.create_collection(
            collection_name=name,
            vectors_config={
                _DENSE: models.VectorParams(size=self._dim, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={
                _SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
        # Payload index on path makes delete-by-path (re-index cleanup) a keyed
        # operation rather than a full scan.
        await self._client.create_payload_index(
            collection_name=name,
            field_name="path",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        _logger.info("qdrant_collection_created", workspace_id=str(workspace_id))

    async def upsert(self, *, workspace_id: uuid.UUID, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        points = [
            models.PointStruct(
                id=str(record.point_id),
                vector={
                    _DENSE: record.dense,
                    _SPARSE: models.SparseVector(
                        indices=record.sparse.indices, values=record.sparse.values
                    ),
                },
                payload={
                    "path": record.path,
                    "language": record.language.value,
                    "header_path": record.header_path,
                    "kind": record.kind.value,
                    "start_line": record.start_line,
                    "end_line": record.end_line,
                    "content": record.content,
                    "suspect": record.suspect,
                },
            )
            for record in records
        ]
        await self._client.upsert(collection_name=self._collection(workspace_id), points=points)

    async def delete_by_paths(self, *, workspace_id: uuid.UUID, paths: Sequence[str]) -> None:
        name = self._collection(workspace_id)
        if not paths or not await self._client.collection_exists(name):
            return
        await self._client.delete(
            collection_name=name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="path", match=models.MatchAny(any=list(paths)))]
                )
            ),
        )

    async def hybrid_search(
        self,
        *,
        workspace_id: uuid.UUID,
        dense: DenseVector,
        sparse: SparseVector,
        limit: int,
    ) -> list[VectorMatch]:
        name = self._collection(workspace_id)
        if not await self._client.collection_exists(name):
            return []
        sparse_vec = models.SparseVector(indices=sparse.indices, values=sparse.values)
        response = await self._client.query_points(
            collection_name=name,
            prefetch=[
                models.Prefetch(query=dense, using=_DENSE, limit=limit),
                models.Prefetch(query=sparse_vec, using=_SPARSE, limit=limit),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return [self._to_match(point) for point in response.points]

    async def drop(self, workspace_id: uuid.UUID) -> None:
        name = self._collection(workspace_id)
        if await self._client.collection_exists(name):
            await self._client.delete_collection(name)

    @staticmethod
    def _to_match(point: models.ScoredPoint) -> VectorMatch:
        payload = point.payload or {}
        return VectorMatch(
            path=str(payload.get("path", "")),
            language=Language(payload["language"]),
            header_path=str(payload.get("header_path", "")),
            kind=SymbolKind(payload["kind"]),
            start_line=int(payload.get("start_line", 0)),
            end_line=int(payload.get("end_line", 0)),
            content=str(payload.get("content", "")),
            suspect=bool(payload.get("suspect", False)),
            score=float(point.score),
        )
