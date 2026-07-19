"""Postgres adapter for the long-term memory store (M11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import or_, select

from spidey.memory.domain.longterm import (
    Memory,
    MemoryKind,
    MemoryProvenance,
    MemoryScope,
)
from spidey.memory.infrastructure.orm import MemoryRecord

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


class PostgresMemoryStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, memory: Memory) -> None:
        self._session.add(
            MemoryRecord(
                id=memory.id,
                kind=memory.kind.value,
                workspace_id=memory.scope.workspace_id,
                user_id=memory.scope.user_id,
                content=memory.content,
                run_id=memory.provenance.run_id,
                distilled_by=memory.provenance.distilled_by,
                source_refs=memory.provenance.source_refs,
                confidence=memory.confidence,
                use_count=memory.use_count,
                last_used_at=memory.last_used_at,
                created_at=memory.created_at,
                expires_at=memory.expires_at,
                superseded_by=memory.superseded_by,
            )
        )
        await self._session.flush()

    async def get(self, *, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory | None:
        record = await self._session.get(MemoryRecord, memory_id)
        if record is None or record.user_id not in (None, user_id):
            return None
        return _to_memory(record)

    async def list_for_user(self, *, user_id: uuid.UUID, limit: int = 200) -> list[Memory]:
        records = await self._session.scalars(
            select(MemoryRecord)
            .where(MemoryRecord.user_id == user_id)
            .order_by(MemoryRecord.created_at.desc())
            .limit(limit)
        )
        return [_to_memory(r) for r in records]

    async def candidates(
        self, *, kinds: list[MemoryKind], scope: MemoryScope, limit: int = 500
    ) -> list[Memory]:
        stmt = (
            select(MemoryRecord)
            .where(
                MemoryRecord.kind.in_([k.value for k in kinds]),
                MemoryRecord.superseded_by.is_(None),
                # Cross-repo (null workspace) memories are always visible; a
                # workspace memory is visible only within its workspace.
                or_(
                    MemoryRecord.workspace_id.is_(None),
                    MemoryRecord.workspace_id == scope.workspace_id,
                ),
            )
            .order_by(MemoryRecord.confidence.desc())
            .limit(limit)
        )
        records = await self._session.scalars(stmt)
        return [_to_memory(r) for r in records]

    async def record_use(
        self, *, memory_id: uuid.UUID, confidence: float, last_used_at: datetime
    ) -> None:
        record = await self._session.get(MemoryRecord, memory_id)
        if record is not None:
            record.confidence = confidence
            record.use_count += 1
            record.last_used_at = last_used_at
            await self._session.flush()

    async def delete(self, *, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory | None:
        record = await self._session.get(MemoryRecord, memory_id)
        if record is None or record.user_id not in (None, user_id):
            return None
        memory = _to_memory(record)
        await self._session.delete(record)
        await self._session.flush()
        return memory


def _to_memory(record: MemoryRecord) -> Memory:
    return Memory(
        id=record.id,
        kind=MemoryKind(record.kind),
        scope=MemoryScope(workspace_id=record.workspace_id, user_id=record.user_id),
        content=record.content,
        provenance=MemoryProvenance(
            run_id=record.run_id,
            distilled_by=record.distilled_by,
            source_refs=list(record.source_refs or []),
        ),
        confidence=record.confidence,
        use_count=record.use_count,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
        expires_at=record.expires_at,
        superseded_by=record.superseded_by,
    )
