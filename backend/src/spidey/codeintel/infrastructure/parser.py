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
from spidey.codeintel.domain.models import (
    CodeChunk,
    EdgeKind,
    Language,
    ParsedUnit,
    Reference,
    Symbol,
    SymbolKind,
)

if TYPE_CHECKING:
    from tree_sitter import Node

    from spidey.codeintel.domain.languages import LanguageSpec

_MAX_SOURCE_BYTES = 8 * 1024 * 1024
_PARSE_TIMEOUT_SECONDS = 10.0
_MAX_DEPTH = 200
_MODULE_SCOPE = "<module>"

# Identifier-like leaf node types across the enabled grammars; the text of these
# is a name we can resolve against a symbol (M5 edge extraction).
_NAME_LEAVES = frozenset(
    {
        "identifier",
        "type_identifier",
        "field_identifier",
        "property_identifier",
        "namespace_identifier",
        "constant",
    }
)
# Fields tried, in order, to reach a call's callee expression across grammars.
_CALLEE_FIELDS = ("function", "name", "constructor", "type")

# Symbol kinds that can carry an ``inherits`` edge (a base type / trait).
_TYPE_KINDS = frozenset(
    {
        SymbolKind.CLASS,
        SymbolKind.STRUCT,
        SymbolKind.INTERFACE,
        SymbolKind.ENUM,
        SymbolKind.TRAIT,
    }
)


def _identifier_leaves(node: Node) -> list[str]:
    """Identifier-like leaf texts under ``node``, in source order."""
    out: list[str] = []
    _collect_identifiers(node, out)
    return out


def _collect_identifiers(node: Node, out: list[str]) -> None:
    if node.child_count == 0:
        if node.type in _NAME_LEAVES and node.text is not None:
            out.append(node.text.decode("utf-8", "replace"))
        return
    for child in node.children:
        _collect_identifiers(child, out)


def _callee_name(call_node: Node) -> str | None:
    """The rightmost identifier of a call's callee (``a.b.c()`` → ``c``)."""
    target: Node | None = None
    for field_name in _CALLEE_FIELDS:
        found = call_node.child_by_field_name(field_name)
        if found is not None:
            target = found
            break
    if target is None:
        return None
    names = _identifier_leaves(target)
    return names[-1] if names else None


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
        self.references: list[Reference] = []
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
                if child.type in self._spec.call_nodes:
                    self._emit_call(child, scope)
                self._walk(child, scope=scope, depth=depth + 1, top_level=top_level)

    def _current_scope(self, scope: list[tuple[SymbolKind, str]]) -> str:
        return ".".join(n for _, n in scope) or _MODULE_SCOPE

    def _emit_call(self, node: Node, scope: list[tuple[SymbolKind, str]]) -> None:
        callee = _callee_name(node)
        if callee is None:
            return
        self.references.append(
            Reference(
                kind=EdgeKind.CALLS,
                from_qualified_name=self._current_scope(scope),
                target_name=callee,
                line=node.start_point[0] + 1,
            )
        )

    def _emit_inherits(self, node: Node, qualified: str) -> None:
        line = node.start_point[0] + 1
        for base in dict.fromkeys(self._base_names(node)):
            if base == qualified.rsplit(".", 1)[-1]:
                continue  # a type does not inherit itself
            self.references.append(
                Reference(
                    kind=EdgeKind.INHERITS,
                    from_qualified_name=qualified,
                    target_name=base,
                    line=line,
                )
            )

    def _base_names(self, node: Node) -> list[str]:
        names: list[str] = []
        for field_name in self._spec.heritage_fields:
            child = node.child_by_field_name(field_name)
            if child is not None:
                names.extend(_identifier_leaves(child))
        if self._spec.heritage_child_types:
            for child in node.children:
                if child.type in self._spec.heritage_child_types:
                    names.extend(_identifier_leaves(child))
        return names

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
        # Import edges (module → imported name). Name-based resolution keeps only
        # the intra-repo targets; external library names simply resolve to
        # nothing and are dropped when the graph is built.
        line = node.start_point[0] + 1
        for target in dict.fromkeys(_identifier_leaves(node)):
            self.references.append(
                Reference(
                    kind=EdgeKind.IMPORTS,
                    from_qualified_name=_MODULE_SCOPE,
                    target_name=target,
                    line=line,
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
        if kind in _TYPE_KINDS:
            self._emit_inherits(node, qualified)

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
            path=path,
            language=language,
            symbols=extractor.symbols,
            chunks=extractor.chunks,
            references=extractor.references,
        )
