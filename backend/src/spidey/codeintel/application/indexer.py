"""Incremental code indexing (FR-2.1, FR-2.2, FR-1.3).

Diffs the workspace's current file manifest (SHA-256 per file, from M2) against
the hashes last indexed, and re-parses only what changed. Deleted or
no-longer-indexable files have their symbols removed; a file that cannot be
parsed is recorded as indexed-but-empty so it is not retried every pass. The
whole operation is bounded per file (parser timeout + size cap), so one bad
file never stalls the index.

When an embedding pipeline is wired (M4), each re-parsed chunk is also screened
for injection payloads (SEC-PI), embedded (dense + sparse), and upserted into
the per-workspace vector index; stale vectors for changed or removed files are
deleted first so retrieval never returns a ghost of old content.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from spidey.codeintel.application.graph_builder import build_graph
from spidey.codeintel.domain.errors import ParseError
from spidey.codeintel.domain.languages import language_for_path
from spidey.codeintel.domain.models import IndexOutcome, IndexStatus
from spidey.codeintel.domain.ports import VectorRecord
from spidey.platform.logging import get_logger
from spidey.platform.security import looks_like_injection

if TYPE_CHECKING:
    from spidey.codeintel.domain.models import CodeChunk, Language, ManifestEntry
    from spidey.codeintel.domain.ports import (
        DenseEmbedder,
        GraphStore,
        Parser,
        SourceReader,
        SparseEmbedder,
        SymbolStore,
        VectorIndex,
    )

_logger = get_logger("spidey.codeintel.indexer")


@dataclass(frozen=True, slots=True)
class EmbeddingPipeline:
    """The three collaborators that turn chunks into searchable vectors.

    Bundled so the indexer holds one optional dependency: when it is present the
    index embeds and upserts, when absent it does symbol-only indexing (M3). A
    single ``None`` check narrows all three for the type checker.
    """

    dense: DenseEmbedder
    sparse: SparseEmbedder
    vectors: VectorIndex


# Deterministic namespace so a chunk's point id is stable across re-index passes
# (same workspace+path+offset → same id → upsert overwrites, never duplicates).
_POINT_NAMESPACE = uuid.UUID("6f1c8f2e-2d3a-4b5c-8e9f-0a1b2c3d4e5f")


class IndexService:
    def __init__(
        self,
        *,
        store: SymbolStore,
        parser: Parser,
        embedding: EmbeddingPipeline | None = None,
        graph: GraphStore | None = None,
    ) -> None:
        self._store = store
        self._parser = parser
        self._embedding = embedding
        self._graph = graph

    async def reindex(
        self,
        *,
        workspace_id: uuid.UUID,
        manifest: list[ManifestEntry],
        reader: SourceReader,
    ) -> IndexOutcome:
        await self._store.set_status(workspace_id=workspace_id, status=IndexStatus.BUILDING)
        if self._embedding is not None:
            await self._embedding.vectors.ensure_collection(workspace_id)

        indexed = await self._store.indexed_hashes(workspace_id)
        desired = self._desired_index(manifest)

        removed = [path for path in indexed if path not in desired]
        await self._store.remove_files(workspace_id=workspace_id, paths=removed)

        changed = [path for path, (sha, _) in desired.items() if indexed.get(path) != sha]

        # Clear stale vectors for everything about to change or disappear, in one
        # pass, before any re-embed — so a crash mid-pass cannot leave duplicates.
        if self._embedding is not None and (removed or changed):
            await self._embedding.vectors.delete_by_paths(
                workspace_id=workspace_id, paths=[*removed, *changed]
            )

        indexed_count = 0
        skipped_count = 0
        for path in changed:
            sha, language = desired[path]
            if await self._index_file(workspace_id, path, sha, language, reader):
                indexed_count += 1
            else:
                skipped_count += 1

        # Rebuild the graph from the workspace's current symbols + references,
        # in the same transaction, so nodes/edges never drift from the symbols
        # they derive from (ADR-0003). Only when something actually changed.
        if self._graph is not None and (changed or removed):
            await self._rebuild_graph(self._graph, workspace_id)

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

    async def _rebuild_graph(self, graph: GraphStore, workspace_id: uuid.UUID) -> None:
        symbols = await self._store.symbols_with_paths(workspace_id)
        references = await self._store.references(workspace_id)
        nodes, edges = build_graph(symbols, references)
        await graph.rebuild(workspace_id=workspace_id, nodes=nodes, edges=edges)

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
                references=[],
            )
            _logger.info("index_file_unparseable", workspace_id=str(workspace_id), path=path)
            return False
        except OSError:
            _logger.warning("index_file_unreadable", workspace_id=str(workspace_id), path=path)
            return False

        # Screen each chunk for injection payloads and capture its text once
        # (SEC-PI): the flag rides with the chunk into both stores and, at
        # retrieval, into the provenance frame.
        screened = [self._screen(chunk, source) for chunk in unit.chunks]
        chunks = [chunk for chunk, _ in screened]

        await self._store.replace_file(
            workspace_id=workspace_id,
            path=path,
            sha256=sha,
            language=language,
            symbols=unit.symbols,
            chunks=chunks,
            references=unit.references,
        )
        if self._embedding is not None:
            await self._embed_and_upsert(self._embedding, workspace_id, path, language, screened)
        return True

    @staticmethod
    def _screen(chunk: CodeChunk, source: bytes) -> tuple[CodeChunk, str]:
        content = source[chunk.start_byte : chunk.end_byte].decode("utf-8", errors="replace")
        suspect = looks_like_injection(content)
        return chunk.model_copy(update={"suspect": suspect}), content

    @staticmethod
    async def _embed_and_upsert(
        embedding: EmbeddingPipeline,
        workspace_id: uuid.UUID,
        path: str,
        language: Language,
        screened: list[tuple[CodeChunk, str]],
    ) -> None:
        if not screened:
            return
        # Embed the header path together with the body so the qualified name
        # ("module > Class > method") shapes the vector, not just the code text.
        texts = [f"{chunk.header_path}\n{content}" for chunk, content in screened]
        dense = embedding.dense.embed_documents(texts)
        sparse = embedding.sparse.embed_documents(texts)
        records = [
            VectorRecord(
                point_id=uuid.uuid5(_POINT_NAMESPACE, f"{workspace_id}:{path}:{chunk.start_byte}"),
                dense=dense_vec,
                sparse=sparse_vec,
                path=path,
                language=language,
                header_path=chunk.header_path,
                kind=chunk.kind,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=content,
                suspect=chunk.suspect,
            )
            for (chunk, content), dense_vec, sparse_vec in zip(screened, dense, sparse, strict=True)
        ]
        await embedding.vectors.upsert(workspace_id=workspace_id, records=records)
