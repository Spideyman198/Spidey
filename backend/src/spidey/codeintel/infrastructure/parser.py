"""Tree-sitter parser adapter: symbol extraction + syntax-aware chunking.

Resource bounds (SEC — parser DoS): the C parse runs under a wall-clock
timeout and a defensive byte cap; the Python AST walk is depth-limited. The M2
size cap already keeps oversized files out of indexing, so these are the second
line of defence against a pathological file stalling an index pass.
"""

from __future__ import annotations

import functools
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import TYPE_CHECKING

import tree_sitter_go
import tree_sitter_java
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_rust
import tree_sitter_typescript
from tree_sitter import Language as TSLanguage
from tree_sitter import Parser as TSParser

from spidey.codeintel.domain.errors import ParseError
from spidey.codeintel.domain.languages import LANGUAGE_SPECS
from spidey.codeintel.domain.models import CodeChunk, Language, ParsedUnit, Symbol, SymbolKind

if TYPE_CHECKING:
    from tree_sitter import Node

    from spidey.codeintel.domain.languages import LanguageSpec

_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_PARSE_TIMEOUT_SECONDS = 10.0
_MAX_DEPTH = 200

# Grammar capsules come bundled in each package's wheel — no runtime download,
# so parsing works offline and under a read-only container rootfs. Adding a
# language is a new dependency plus one entry here and in the domain registry.
_GRAMMARS = {
    Language.PYTHON: tree_sitter_python.language,
    Language.JAVASCRIPT: tree_sitter_javascript.language,
    Language.TYPESCRIPT: tree_sitter_typescript.language_typescript,
    Language.GO: tree_sitter_go.language,
    Language.JAVA: tree_sitter_java.language,
    Language.RUST: tree_sitter_rust.language,
}


@functools.cache
def _parser_for(language: Language) -> TSParser:
    return TSParser(TSLanguage(_GRAMMARS[language]()))


def _resolve_name(node: Node, kind: SymbolKind) -> str | None:
    named = node.child_by_field_name("name")
    if named is not None and named.text is not None:
        return named.text.decode("utf-8", "replace")
    # Rust impl blocks name the type they implement, not a 'name' field.
    if kind is SymbolKind.CLASS:
        typed = node.child_by_field_name("type")
        if typed is not None and typed.text is not None:
            return typed.text.decode("utf-8", "replace")
    return None


def _refine_go_type(node: Node, kind: SymbolKind) -> SymbolKind:
    # Go `type_spec` covers structs and interfaces; look at the declared type.
    for child in node.children:
        if child.type == "interface_type":
            return SymbolKind.INTERFACE
        if child.type == "struct_type":
            return SymbolKind.STRUCT
    return kind


def _first_definition_child(node: Node, spec: LanguageSpec) -> Node | None:
    """Depth-first earliest descendant that begins a nested definition."""
    best: Node | None = None
    stack = list(node.children)
    while stack:
        current = stack.pop()
        if current.type in spec.definitions:
            if best is None or current.start_byte < best.start_byte:
                best = current
            continue  # its own nested defs are handled when it is chunked
        stack.extend(current.children)
    return best


class _Extractor:
    def __init__(self, spec: LanguageSpec, source_len: int) -> None:
        self._spec = spec
        self._source_len = source_len
        self.symbols: list[Symbol] = []
        self.chunks: list[CodeChunk] = []
        self._first_top_level: int | None = None
        self._first_top_level_line: int = 1

    def run(self, root: Node) -> None:
        self._walk(root, scope=[], depth=0, top_level=True)
        # Module preamble chunk: imports and top-level code before the first
        # definition (or the whole file when there are no definitions).
        if self._first_top_level is not None:
            end_byte, end_line = self._first_top_level, self._first_top_level_line
        else:
            end_byte, end_line = self._source_len, root.end_point[0] + 1
        if end_byte > 0:
            self.chunks.append(
                CodeChunk(
                    header_path="<module>",
                    kind=SymbolKind.IMPORT,
                    start_line=1,
                    end_line=max(1, end_line),
                    start_byte=0,
                    end_byte=end_byte,
                )
            )
        self.chunks.sort(key=lambda c: c.start_byte)

    def _walk(
        self, node: Node, *, scope: list[tuple[SymbolKind, str]], depth: int, top_level: bool
    ) -> None:
        if depth > _MAX_DEPTH:
            return
        for child in node.children:
            if child.type in self._spec.import_nodes:
                self._emit_import(child)
            elif child.type in self._spec.definitions:
                self._emit_definition(child, scope=scope, depth=depth, top_level=top_level)
            else:
                self._walk(child, scope=scope, depth=depth + 1, top_level=top_level)

    def _emit_import(self, node: Node) -> None:
        text = node.text.decode("utf-8", "replace").strip() if node.text is not None else ""
        self.symbols.append(
            Symbol(
                kind=SymbolKind.IMPORT,
                name=text.splitlines()[0][:200] if text else "import",
                qualified_name=text[:400],
                parent=None,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                reference=text[:400],
            )
        )

    def _emit_definition(
        self, node: Node, *, scope: list[tuple[SymbolKind, str]], depth: int, top_level: bool
    ) -> None:
        kind = self._spec.definitions[node.type]
        name = _resolve_name(node, kind)
        if name is None:
            self._walk(node, scope=scope, depth=depth + 1, top_level=top_level)
            return
        if node.type == "type_spec":
            kind = _refine_go_type(node, kind)
        if (
            kind is SymbolKind.FUNCTION
            and scope
            and scope[-1][0] in self._spec.method_container_kinds
        ):
            kind = SymbolKind.METHOD

        qualified = ".".join([n for _, n in scope] + [name])
        parent = ".".join(n for _, n in scope) or None
        self.symbols.append(
            Symbol(
                kind=kind,
                name=name,
                qualified_name=qualified,
                parent=parent,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
            )
        )

        if top_level and (self._first_top_level is None or node.start_byte < self._first_top_level):
            self._first_top_level = node.start_byte
            self._first_top_level_line = node.start_point[0] + 1

        nested = _first_definition_child(node, self._spec)
        chunk_end = nested.start_byte if nested is not None else node.end_byte
        chunk_end_line = (nested.start_point[0] if nested is not None else node.end_point[0]) + 1
        self.chunks.append(
            CodeChunk(
                header_path=qualified,
                kind=kind,
                start_line=node.start_point[0] + 1,
                end_line=chunk_end_line,
                start_byte=node.start_byte,
                end_byte=chunk_end,
            )
        )
        self._walk(node, scope=[*scope, (kind, name)], depth=depth + 1, top_level=False)


class TreeSitterParser:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ts-parse")

    def parse(self, *, path: str, language: Language, source: bytes) -> ParsedUnit:
        if len(source) > _MAX_SOURCE_BYTES:
            raise ParseError("source exceeds the parser size limit", path=path)
        spec = LANGUAGE_SPECS[language]
        try:
            unit = self._pool.submit(self._parse_sync, path, language, spec, source).result(
                timeout=_PARSE_TIMEOUT_SECONDS
            )
        except FutureTimeout as exc:
            # The C parse leaked a worker thread; replace the pool so the next
            # file gets a fresh one, and surface a bounded failure.
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ts-parse")
            raise ParseError("parsing timed out", path=path) from exc
        return unit

    @staticmethod
    def _parse_sync(path: str, language: Language, spec: LanguageSpec, source: bytes) -> ParsedUnit:
        tree = _parser_for(language).parse(source)
        extractor = _Extractor(spec, len(source))
        extractor.run(tree.root_node)
        return ParsedUnit(
            path=path, language=language, symbols=extractor.symbols, chunks=extractor.chunks
        )
