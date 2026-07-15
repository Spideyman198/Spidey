"""Code-intelligence domain model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Language(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    JAVA = "java"
    RUST = "rust"


class SymbolKind(StrEnum):
    """Language-neutral symbol categories. Each language maps its native node
    types onto this set (docs/06); `import` captures every dependency form."""

    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    INTERFACE = "interface"
    STRUCT = "struct"
    ENUM = "enum"
    TRAIT = "trait"
    IMPORT = "import"


class Symbol(BaseModel):
    """A definition (or import) extracted from a source file.

    ``qualified_name`` is the dotted header path of enclosing scopes
    (``module > Class > method``) that gives retrieval its context and the M5
    graph its node identity. Line and byte spans map back to source exactly.
    """

    model_config = ConfigDict(frozen=True)

    kind: SymbolKind
    name: str
    qualified_name: str
    parent: str | None
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    # For imports: the referenced module/target text; None otherwise.
    reference: str | None = None


class CodeChunk(BaseModel):
    """A syntax-aligned slice of source for embedding (M4).

    Chunks are non-overlapping: a definition that contains nested definitions
    contributes only its own preamble (signature + body up to the first nested
    definition), and the nested definitions are separate chunks. ``suspect`` is
    set when index-time screening finds an injection-pattern payload (SEC-PI).
    """

    model_config = ConfigDict(frozen=True)

    header_path: str
    kind: SymbolKind
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    suspect: bool = False


class SearchHit(BaseModel):
    """One retrieval result with full provenance (docs/06)."""

    model_config = ConfigDict(frozen=True)

    path: str
    language: Language
    header_path: str
    kind: SymbolKind
    start_line: int
    end_line: int
    content: str
    score: float
    suspect: bool
    # How the hit was found: 'dense', 'sparse', 'hybrid', or 'symbol'.
    source: str


class ParsedUnit(BaseModel):
    """The full parse result for one file."""

    model_config = ConfigDict(frozen=True)

    path: str
    language: Language
    symbols: list[Symbol] = Field(default_factory=list[Symbol])
    chunks: list[CodeChunk] = Field(default_factory=list[CodeChunk])


class ManifestEntry(BaseModel):
    """Input to indexing: one indexable file and its content hash (from M2)."""

    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str


class IndexStatus(StrEnum):
    PENDING = "pending"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class IndexOutcome(BaseModel):
    """Summary of an incremental index pass."""

    model_config = ConfigDict(frozen=True)

    status: IndexStatus
    files_indexed: int
    files_removed: int
    files_skipped: int
    symbol_count: int
    chunk_count: int
    updated_at: datetime


class IndexState(BaseModel):
    """Current persisted index state for a workspace (read model)."""

    model_config = ConfigDict(frozen=True)

    status: IndexStatus
    file_count: int
    symbol_count: int
    chunk_count: int
    updated_at: datetime
