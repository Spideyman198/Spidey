"""Code-intelligence ports.

The context is deliberately decoupled from ``workspaces``: it reads source
through the :class:`SourceReader` port, which the worker satisfies with an
adapter over the workspace ``SafeFileSystem``. codeintel therefore never
imports workspaces, preserving bounded-context independence.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from spidey.codeintel.domain.models import (
        CodeChunk,
        IndexState,
        IndexStatus,
        Language,
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


class SymbolStore(Protocol):
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
