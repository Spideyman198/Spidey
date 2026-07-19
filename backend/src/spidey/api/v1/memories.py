"""Long-term memory management API (M11, FR-5.3).

User sovereignty over memory: a user can list what the system remembers about
them, delete any of it (record *and* vector), and explicitly teach a fact
("remember this"). The explicit-write path still passes the write gate, so a user
cannot inject an imperative into memory either. Recall and distillation are
internal to the run engine; this surface is inspection and control only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from spidey.api.deps import CurrentUser, MemoryServiceDep
from spidey.memory.domain import MemoryCandidate, MemoryKind, MemoryProvenance, MemoryScope
from spidey.platform.errors import NotFoundError, ValidationFailedError

router = APIRouter(prefix="/memories", tags=["memory"])


class MemoryResponse(BaseModel):
    id: uuid.UUID
    kind: MemoryKind
    content: str
    confidence: float
    use_count: int
    created_at: datetime


class RememberRequest(BaseModel):
    content: str = Field(min_length=3, max_length=2000)
    kind: MemoryKind = MemoryKind.SEMANTIC


@router.get("", response_model=list[MemoryResponse], summary="List my long-term memories")
async def list_memories(service: MemoryServiceDep, user: CurrentUser) -> list[MemoryResponse]:
    memories = await service.list_for_user(user_id=user.id)
    return [
        MemoryResponse(
            id=m.id,
            kind=m.kind,
            content=m.content,
            confidence=m.confidence,
            use_count=m.use_count,
            created_at=m.created_at,
        )
        for m in memories
    ]


@router.post(
    "",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Teach a fact ('remember this') — still screened by the write gate",
)
async def remember(
    body: RememberRequest, service: MemoryServiceDep, user: CurrentUser
) -> MemoryResponse:
    candidate = MemoryCandidate(
        kind=body.kind,
        content=body.content,
        scope=MemoryScope(user_id=user.id),
        provenance=MemoryProvenance(distilled_by="user"),
        confidence=0.9,  # a user-taught fact starts trusted, but not absolute
    )
    written = await service.write([candidate])
    if not written:
        # The gate rejected it (imperative / secret / duplicate / bad scope).
        raise ValidationFailedError("the memory was rejected by the write gate")
    m = written[0]
    return MemoryResponse(
        id=m.id,
        kind=m.kind,
        content=m.content,
        confidence=m.confidence,
        use_count=m.use_count,
        created_at=m.created_at,
    )


@router.delete(
    "/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a memory (removes record and vector)",
)
async def delete_memory(memory_id: uuid.UUID, service: MemoryServiceDep, user: CurrentUser) -> None:
    if not await service.delete(user_id=user.id, memory_id=memory_id):
        raise NotFoundError("memory not found")
