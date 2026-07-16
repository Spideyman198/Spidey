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
    types onto this set (docs/06); `import` captures every dependency form.
    `module` is never a parsed symbol — it labels the per-file node the M5
    graph hangs ``defines``/``imports`` edges on."""

    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    INTERFACE = "interface"
    STRUCT = "struct"
    ENUM = "enum"
    TRAIT = "trait"
    IMPORT = "import"
    MODULE = "module"


class EdgeKind(StrEnum):
    """Knowledge-graph edge types (FR-2.5): a module ``defines`` a symbol and
    ``imports`` a target; a symbol ``calls`` another and a type ``inherits`` a
    base. Directed source→target."""

    DEFINES = "defines"
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"


class Reference(BaseModel):
    """An unresolved edge captured while parsing one file (M5).

    The graph builder later resolves ``target_name`` to a concrete node by name,
    scoped to the workspace. ``from_qualified_name`` is the enclosing definition
    (empty for module-level references such as imports).
    """

    model_config = ConfigDict(frozen=True)

    kind: EdgeKind
    from_qualified_name: str
    target_name: str
    line: int


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


class CodeSearchResult(BaseModel):
    """Search output: ranked hits plus graph-expansion facts (docs/06)."""

    model_config = ConfigDict(frozen=True)

    hits: list[SearchHit] = Field(default_factory=list[SearchHit])
    graph_facts: list[str] = Field(default_factory=list[str])


class ParsedUnit(BaseModel):
    """The full parse result for one file."""

    model_config = ConfigDict(frozen=True)

    path: str
    language: Language
    symbols: list[Symbol] = Field(default_factory=list[Symbol])
    chunks: list[CodeChunk] = Field(default_factory=list[CodeChunk])
    references: list[Reference] = Field(default_factory=list[Reference])


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


class GraphNode(BaseModel):
    """A node in a workspace's code knowledge graph (ADR-0003).

    Identity within a workspace is ``(path, qualified_name)`` — the same
    qualified name in two files is two nodes. A module node uses the sentinel
    qualified name ``<module>`` so file-level ``defines``/``imports`` edges have
    a source.
    """

    model_config = ConfigDict(frozen=True)

    path: str
    qualified_name: str
    name: str
    kind: SymbolKind
    start_line: int


class GraphEdge(BaseModel):
    """A resolved, directed edge between two nodes of the same workspace."""

    model_config = ConfigDict(frozen=True)

    src_path: str
    src_qualified_name: str
    dst_path: str
    dst_qualified_name: str
    kind: EdgeKind
    # Source line of the reference (call/import site); None for structural edges.
    line: int | None = None


class GraphNeighbor(BaseModel):
    """A node reached from a query seed, with how it was reached (read model)."""

    model_config = ConfigDict(frozen=True)

    node: GraphNode
    edge_kind: EdgeKind
    # Hops from the seed (1 = direct neighbor). Drives retrieval score decay.
    distance: int
    # The immediate predecessor on the path from the seed, for fact rendering.
    via_qualified_name: str
    via_path: str
    line: int | None = None
    # True when the edge points via → node (e.g. via *calls* node); False when it
    # points node → via (node *calls* via). Makes rendered facts directional.
    outgoing: bool = True

    def as_fact(self) -> str:
        """A one-line, directional relationship statement with provenance."""
        verb = _EDGE_VERB.get((self.edge_kind, self.outgoing), self.edge_kind.value)
        loc = f"{self.node.path}:{self.node.start_line}"
        if self.outgoing:
            return f"{self.via_qualified_name} {verb} {self.node.qualified_name} ({loc})"
        return f"{self.node.qualified_name} {verb} {self.via_qualified_name} ({loc})"


# Directional English for an (edge_kind, via-is-source?) pair.
_EDGE_VERB: dict[tuple[EdgeKind, bool], str] = {
    (EdgeKind.CALLS, True): "calls",
    (EdgeKind.CALLS, False): "calls",
    (EdgeKind.INHERITS, True): "inherits",
    (EdgeKind.INHERITS, False): "inherits",
    (EdgeKind.IMPORTS, True): "imports",
    (EdgeKind.IMPORTS, False): "imports",
    (EdgeKind.DEFINES, True): "defines",
    (EdgeKind.DEFINES, False): "defines",
}
