"""Incremental code indexing (FR-2.1, FR-2.2, FR-1.3).

Diffs the workspace's current file manifest (SHA-256 per file, from M2) against
the hashes last indexed, and re-parses only what changed. Deleted or
no-longer-indexable files have their symbols removed; a file that cannot be
parsed is recorded as indexed-but-empty so it is not retried every pass. The
whole operation is bounded per file (parser timeout + size cap), so one bad
file never stalls the index.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spidey.codeintel.domain.errors import ParseError
from spidey.codeintel.domain.languages import language_for_path
from spidey.codeintel.domain.models import IndexOutcome, IndexStatus
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    import uuid

    from spidey.codeintel.domain.models import Language, ManifestEntry
    from spidey.codeintel.domain.ports import Parser, SourceReader, SymbolStore

_logger = get_logger("spidey.codeintel.indexer")


class IndexService:
    def __init__(self, *, store: SymbolStore, parser: Parser) -> None:
        self._store = store
        self._parser = parser

    async def reindex(
        self,
        *,
        workspace_id: uuid.UUID,
        manifest: list[ManifestEntry],
        reader: SourceReader,
    ) -> IndexOutcome:
        await self._store.set_status(workspace_id=workspace_id, status=IndexStatus.BUILDING)

        indexed = await self._store.indexed_hashes(workspace_id)
        desired = self._desired_index(manifest)

        removed = [path for path in indexed if path not in desired]
        await self._store.remove_files(workspace_id=workspace_id, paths=removed)

        changed = [path for path, (sha, _) in desired.items() if indexed.get(path) != sha]

        indexed_count = 0
        skipped_count = 0
        for path in changed:
            sha, language = desired[path]
            if await self._index_file(workspace_id, path, sha, language, reader):
                indexed_count += 1
            else:
                skipped_count += 1

        file_count, symbol_count, chunk_count = await self._store.counts(workspace_id)
        await self._store.set_status(
            workspace_id=workspace_id,
            status=IndexStatus.READY,
            file_count=file_count,
            symbol_count=symbol_count,
            chunk_count=chunk_count,
        )
        return IndexOutcome(
            status=IndexStatus.READY,
            files_indexed=indexed_count,
            files_removed=len(removed),
            files_skipped=skipped_count,
            symbol_count=symbol_count,
            chunk_count=chunk_count,
            updated_at=datetime.now(tz=UTC),
        )

    @staticmethod
    def _desired_index(
        manifest: list[ManifestEntry],
    ) -> dict[str, tuple[str, Language]]:
        desired: dict[str, tuple[str, Language]] = {}
        for entry in manifest:
            language = language_for_path(entry.path)
            if language is not None:
                desired[entry.path] = (entry.sha256, language)
        return desired

    async def _index_file(
        self,
        workspace_id: uuid.UUID,
        path: str,
        sha: str,
        language: Language,
        reader: SourceReader,
    ) -> bool:
        try:
            # SourceReader port, not raw FS: reads go through the workspace
            # SafeFileSystem adapter (SEC-FS), which is exactly what the rule wants.
            source = reader.read_bytes(path)  # nosemgrep: spidey-agents-no-direct-file-io
            unit = self._parser.parse(path=path, language=language, source=source)
        except ParseError:
            # Record as indexed-but-empty so a persistently unparseable file is
            # not re-attempted every pass; its stale symbols are cleared.
            await self._store.replace_file(
                workspace_id=workspace_id,
                path=path,
                sha256=sha,
                language=language,
                symbols=[],
                chunks=[],
            )
            _logger.info("index_file_unparseable", workspace_id=str(workspace_id), path=path)
            return False
        except OSError:
            _logger.warning("index_file_unreadable", workspace_id=str(workspace_id), path=path)
            return False

        await self._store.replace_file(
            workspace_id=workspace_id,
            path=path,
            sha256=sha,
            language=language,
            symbols=unit.symbols,
            chunks=unit.chunks,
        )
        return True
