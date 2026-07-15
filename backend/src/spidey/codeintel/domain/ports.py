"""Code-intelligence ports.

The context is deliberately decoupled from ``workspaces``: it reads source
through the :class:`SourceReader` port, which the worker satisfies with an
adapter over the workspace ``SafeFileSystem``. codeintel therefore never
imports workspaces, preserving bounded-context independence.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from spidey.codeintel.domain.models import Language, SymbolKind
from spidey.platform.vectors import DenseVector, SparseVector

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spidey.codeintel.domain.models import (
        CodeChunk,
        IndexState,
        IndexStatus,
        ParsedUnit,
        Symbol,
    )


class SourceReader(Protocol):
    """Reads file bytes from a workspace under containment guarantees.

    Implemented by a worker-side adapter over the workspace SafeFileSystem, so
    every read here inherits SEC-FS traversal protection.
    """

    def read_bytes(self, path: str) -> bytes: ...


class Parser(Protocol):
    """Parses source bytes into symbols and chunks for a given language.

    Must be resource-bounded: a pathological input raises rather than hanging,
    so one file can never stall an index pass (SEC — parser DoS).
    """

    def parse(self, *, path: str, language: Language, source: bytes) -> ParsedUnit: ...


class SymbolLookup(Protocol):
    """Read-only symbol name lookup — all the search path needs from the store.

    Segregated from the full :class:`SymbolStore` so a read-only consumer
    (SearchService) depends only on what it uses, and its tests fake only this.
    """

    async def symbols_for_terms(
        self, *, workspace_id: uuid.UUID, terms: Sequence[str]
    ) -> list[Symbol]:
        """Symbols whose ``name`` is exactly one of ``terms`` (case-insensitive).

        Drives the lexical-precision boost in hybrid search: an exact identifier
        match should surface even when the embedding ranks it low.
        """
        ...


class SymbolStore(SymbolLookup, Protocol):
    """Persistence for the code index: per-file symbols and chunks, the
    indexed-file hashes that drive incremental re-indexing, and the per-
    workspace index snapshot."""

    async def indexed_hashes(self, workspace_id: uuid.UUID) -> dict[str, str]:
        """Map of path → indexed SHA-256 for the workspace's current index."""
        ...

    async def replace_file(
        self,
        *,
        workspace_id: uuid.UUID,
        path: str,
        sha256: str,
        language: Language,
        symbols: list[Symbol],
        chunks: list[CodeChunk],
    ) -> None:
        """Atomically replace a file's symbols, chunks, and indexed hash."""
        ...

    async def remove_files(self, *, workspace_id: uuid.UUID, paths: list[str]) -> None: ...

    async def set_status(
        self,
        *,
        workspace_id: uuid.UUID,
        status: IndexStatus,
        symbol_count: int | None = None,
        chunk_count: int | None = None,
        file_count: int | None = None,
    ) -> None: ...

    async def counts(self, workspace_id: uuid.UUID) -> tuple[int, int, int]:
        """Current (file_count, symbol_count, chunk_count) for the workspace."""
        ...

    async def list_symbols(
        self, *, workspace_id: uuid.UUID, path: str | None = None
    ) -> list[Symbol]: ...

    async def get_state(self, workspace_id: uuid.UUID) -> IndexState | None:
        """The persisted index snapshot for a workspace, or None if never indexed."""
        ...


class DenseEmbedder(Protocol):
    """Consumer-side port for dense embeddings (satisfied by the llm adapter).

    Defined here, not imported from ``llm``, so codeintel depends only on the
    shape it needs — bounded-context independence via dependency inversion.
    """

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[DenseVector]: ...

    def embed_query(self, text: str) -> DenseVector: ...


class SparseEmbedder(Protocol):
    """Consumer-side port for sparse (BM25) embeddings."""

    def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]: ...

    def embed_query(self, text: str) -> SparseVector: ...


class VectorRecord(BaseModel):
    """One chunk's vectors plus the payload the store returns on a hit.

    ``point_id`` is a deterministic UUID5 of ``workspace_id:path:start_byte`` so
    re-indexing a file overwrites its prior points rather than duplicating them.
    Content lives in the payload so a search needs no filesystem read.
    """

    model_config = ConfigDict(frozen=True)

    point_id: uuid.UUID
    dense: DenseVector
    sparse: SparseVector
    path: str
    language: Language
    header_path: str
    kind: SymbolKind
    start_line: int
    end_line: int
    content: str
    suspect: bool


class VectorMatch(BaseModel):
    """A scored payload returned by the vector store for a hybrid query."""

    model_config = ConfigDict(frozen=True)

    path: str
    language: Language
    header_path: str
    kind: SymbolKind
    start_line: int
    end_line: int
    content: str
    suspect: bool
    score: float


class VectorSearcher(Protocol):
    """Read-only hybrid query — all the search path needs from the vector store.

    Segregated from :class:`VectorIndex` so SearchService (and its tests) depend
    only on the query surface, not the write/lifecycle surface.
    """

    async def hybrid_search(
        self,
        *,
        workspace_id: uuid.UUID,
        dense: DenseVector,
        sparse: SparseVector,
        limit: int,
    ) -> list[VectorMatch]: ...


class VectorIndex(VectorSearcher, Protocol):
    """Per-workspace hybrid (dense + sparse/BM25) vector store.

    Collections are isolated per workspace so a search can never cross a tenant
    boundary. The adapter fuses dense and sparse rankings server-side (RRF).
    """

    async def ensure_collection(self, workspace_id: uuid.UUID) -> None:
        """Create the workspace collection with named dense+bm25 vectors if absent."""
        ...

    async def upsert(self, *, workspace_id: uuid.UUID, records: Sequence[VectorRecord]) -> None: ...

    async def delete_by_paths(self, *, workspace_id: uuid.UUID, paths: Sequence[str]) -> None:
        """Remove every point whose payload path is in ``paths`` (re-index cleanup)."""
        ...

    async def drop(self, workspace_id: uuid.UUID) -> None:
        """Delete the workspace collection entirely (workspace teardown)."""
        ...
