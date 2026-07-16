"""Postgres adapter for the code-index symbol store."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from spidey.codeintel.domain.models import (
    EdgeKind,
    IndexState,
    IndexStatus,
    Language,
    Reference,
    Symbol,
    SymbolKind,
)
from spidey.codeintel.infrastructure.orm import (
    CodeChunkRecord,
    CodeReferenceRecord,
    IndexedFileRecord,
    IndexSnapshotRecord,
    SymbolRecord,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from spidey.codeintel.domain.models import CodeChunk


class PostgresSymbolStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def indexed_hashes(self, workspace_id: uuid.UUID) -> dict[str, str]:
        rows = await self._session.execute(
            select(IndexedFileRecord.path, IndexedFileRecord.sha256).where(
                IndexedFileRecord.workspace_id == workspace_id
            )
        )
        return {row.path: row.sha256 for row in rows}

    async def replace_file(
        self,
        *,
        workspace_id: uuid.UUID,
        path: str,
        sha256: str,
        language: Language,
        symbols: list[Symbol],
        chunks: list[CodeChunk],
        references: list[Reference],
    ) -> None:
        await self._delete_file_rows(workspace_id, [path])
        self._session.add_all(
            SymbolRecord(
                workspace_id=workspace_id,
                path=path,
                language=language.value,
                kind=s.kind.value,
                name=s.name,
                qualified_name=s.qualified_name,
                parent=s.parent,
                start_line=s.start_line,
                end_line=s.end_line,
                start_byte=s.start_byte,
                end_byte=s.end_byte,
                reference=s.reference,
            )
            for s in symbols
        )
        self._session.add_all(
            CodeChunkRecord(
                workspace_id=workspace_id,
                path=path,
                language=language.value,
                header_path=c.header_path,
                kind=c.kind.value,
                start_line=c.start_line,
                end_line=c.end_line,
                start_byte=c.start_byte,
                end_byte=c.end_byte,
                is_suspect=c.suspect,
            )
            for c in chunks
        )
        self._session.add_all(
            CodeReferenceRecord(
                workspace_id=workspace_id,
                path=path,
                kind=r.kind.value,
                from_qualified_name=r.from_qualified_name,
                target_name=r.target_name,
                line=r.line,
            )
            for r in references
        )
        # Upsert the indexed-file hash so a re-run detects no change.
        await self._session.execute(
            pg_insert(IndexedFileRecord)
            .values(workspace_id=workspace_id, path=path, sha256=sha256, language=language.value)
            .on_conflict_do_update(
                index_elements=[IndexedFileRecord.workspace_id, IndexedFileRecord.path],
                set_={"sha256": sha256, "language": language.value},
            )
        )
        await self._session.flush()

    async def remove_files(self, *, workspace_id: uuid.UUID, paths: list[str]) -> None:
        if paths:
            await self._delete_file_rows(workspace_id, paths)
            await self._session.flush()

    async def _delete_file_rows(self, workspace_id: uuid.UUID, paths: list[str]) -> None:
        for model in (SymbolRecord, CodeChunkRecord, CodeReferenceRecord, IndexedFileRecord):
            await self._session.execute(
                delete(model).where(model.workspace_id == workspace_id, model.path.in_(paths))
            )

    async def set_status(
        self,
        *,
        workspace_id: uuid.UUID,
        status: IndexStatus,
        symbol_count: int | None = None,
        chunk_count: int | None = None,
        file_count: int | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status.value}
        if symbol_count is not None:
            values["symbol_count"] = symbol_count
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        if file_count is not None:
            values["file_count"] = file_count
        await self._session.execute(
            pg_insert(IndexSnapshotRecord)
            .values(workspace_id=workspace_id, **values)
            .on_conflict_do_update(index_elements=[IndexSnapshotRecord.workspace_id], set_=values)
        )
        await self._session.flush()

    async def counts(self, workspace_id: uuid.UUID) -> tuple[int, int, int]:
        files = await self._session.scalar(
            select(func.count())
            .select_from(IndexedFileRecord)
            .where(IndexedFileRecord.workspace_id == workspace_id)
        )
        symbols = await self._session.scalar(
            select(func.count())
            .select_from(SymbolRecord)
            .where(SymbolRecord.workspace_id == workspace_id)
        )
        chunks = await self._session.scalar(
            select(func.count())
            .select_from(CodeChunkRecord)
            .where(CodeChunkRecord.workspace_id == workspace_id)
        )
        return int(files or 0), int(symbols or 0), int(chunks or 0)

    async def get_state(self, workspace_id: uuid.UUID) -> IndexState | None:
        record = await self._session.get(IndexSnapshotRecord, workspace_id)
        if record is None:
            return None
        return IndexState(
            status=IndexStatus(record.status),
            file_count=record.file_count,
            symbol_count=record.symbol_count,
            chunk_count=record.chunk_count,
            updated_at=record.updated_at,
        )

    async def list_symbols(
        self, *, workspace_id: uuid.UUID, path: str | None = None
    ) -> list[Symbol]:
        query = (
            select(SymbolRecord)
            .where(SymbolRecord.workspace_id == workspace_id)
            .order_by(SymbolRecord.path, SymbolRecord.start_line)
        )
        if path is not None:
            query = query.where(SymbolRecord.path == path)
        records = await self._session.scalars(query)
        return [self._to_symbol(r) for r in records]

    async def symbols_for_terms(
        self, *, workspace_id: uuid.UUID, terms: Sequence[str]
    ) -> list[Symbol]:
        lowered = {t.lower() for t in terms if t}
        if not lowered:
            return []
        records = await self._session.scalars(
            select(SymbolRecord).where(
                SymbolRecord.workspace_id == workspace_id,
                func.lower(SymbolRecord.name).in_(lowered),
            )
        )
        return [self._to_symbol(r) for r in records]

    async def symbols_with_paths(self, workspace_id: uuid.UUID) -> list[tuple[str, Symbol]]:
        records = await self._session.scalars(
            select(SymbolRecord)
            .where(SymbolRecord.workspace_id == workspace_id)
            .order_by(SymbolRecord.path, SymbolRecord.start_line)
        )
        return [(r.path, self._to_symbol(r)) for r in records]

    async def references(self, workspace_id: uuid.UUID) -> list[tuple[str, Reference]]:
        records = await self._session.scalars(
            select(CodeReferenceRecord).where(CodeReferenceRecord.workspace_id == workspace_id)
        )
        return [
            (
                r.path,
                Reference(
                    kind=EdgeKind(r.kind),
                    from_qualified_name=r.from_qualified_name,
                    target_name=r.target_name,
                    line=r.line,
                ),
            )
            for r in records
        ]

    @staticmethod
    def _to_symbol(r: SymbolRecord) -> Symbol:
        return Symbol(
            kind=SymbolKind(r.kind),
            name=r.name,
            qualified_name=r.qualified_name,
            parent=r.parent,
            start_line=r.start_line,
            end_line=r.end_line,
            start_byte=r.start_byte,
            end_byte=r.end_byte,
            reference=r.reference,
        )
