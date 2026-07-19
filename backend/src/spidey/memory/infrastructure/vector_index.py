"""Qdrant adapter for the memory semantic index (M11, docs/07).

A single ``memories`` collection with one dense vector and a small payload
(``kind`` + optional ``workspace_id``) so recall can filter by kind and scope.
Cross-repo (semantic) memories carry no ``workspace_id`` payload, so the scope
filter admits them for every workspace while a workspace memory is admitted only
for its own workspace — the vector-side half of the double scope filter.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from qdrant_client import models

from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

    from spidey.memory.domain.longterm import MemoryKind, MemoryScope

_logger = get_logger("spidey.memory.qdrant")
_COLLECTION = "memories"


class QdrantMemoryIndex:
    def __init__(self, *, client: AsyncQdrantClient, dense_dim: int) -> None:
        self._client = client
        self._dim = dense_dim

    async def ensure_collection(self) -> None:
        if await self._client.collection_exists(_COLLECTION):
            return
        await self._client.create_collection(
            collection_name=_COLLECTION,
            vectors_config=models.VectorParams(size=self._dim, distance=models.Distance.COSINE),
        )
        _logger.info("qdrant_memory_collection_created")

    async def upsert(
        self,
        *,
        memory_id: uuid.UUID,
        vector: list[float],
        kind: MemoryKind,
        scope: MemoryScope,
    ) -> None:
        payload: dict[str, str] = {"kind": kind.value}
        if scope.workspace_id is not None:
            payload["workspace_id"] = str(scope.workspace_id)
        await self._client.upsert(
            collection_name=_COLLECTION,
            points=[models.PointStruct(id=str(memory_id), vector=vector, payload=payload)],
        )

    async def search(
        self,
        *,
        vector: list[float],
        kinds: list[MemoryKind],
        scope: MemoryScope,
        limit: int,
    ) -> list[tuple[uuid.UUID, float]]:
        # kind is in requested AND (no workspace_id payload OR it equals the query's).
        scope_should: list[models.Condition] = [
            models.IsEmptyCondition(is_empty=models.PayloadField(key="workspace_id"))
        ]
        if scope.workspace_id is not None:
            scope_should.append(
                models.FieldCondition(
                    key="workspace_id",
                    match=models.MatchValue(value=str(scope.workspace_id)),
                )
            )
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="kind", match=models.MatchAny(any=[k.value for k in kinds])
                )
            ],
            should=scope_should,
        )
        response = await self._client.query_points(
            collection_name=_COLLECTION,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=False,
        )
        return [(uuid.UUID(str(point.id)), point.score) for point in response.points]

    async def delete(self, *, memory_id: uuid.UUID) -> None:
        await self._client.delete(
            collection_name=_COLLECTION,
            points_selector=models.PointIdsList(points=[str(memory_id)]),
        )
