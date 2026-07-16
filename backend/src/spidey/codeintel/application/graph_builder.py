"""Resolve parsed symbols + references into knowledge-graph nodes and edges.

Pure and deterministic: it takes the workspace's symbols and captured references
and returns the node/edge sets a :class:`GraphStore` persists. Resolution is
name-based and workspace-scoped (docs/06, ADR-0003) — a reference to ``foo``
links to workspace symbols named ``foo``, preferring a same-file definition and
otherwise linking to every candidate (an over-approximation, the safe direction
for impact sets). External names resolve to nothing and are dropped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.codeintel.domain.models import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    Reference,
    Symbol,
    SymbolKind,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

_MODULE = "<module>"
# Cap fan-out when a name is ambiguous, so one common name can't explode the graph.
_MAX_TARGETS = 8

# Which node kinds a reference of each edge kind may resolve to.
_TARGET_KINDS: dict[EdgeKind, frozenset[SymbolKind]] = {
    EdgeKind.CALLS: frozenset(
        {SymbolKind.FUNCTION, SymbolKind.METHOD, SymbolKind.CLASS, SymbolKind.STRUCT}
    ),
    EdgeKind.INHERITS: frozenset(
        {
            SymbolKind.CLASS,
            SymbolKind.INTERFACE,
            SymbolKind.STRUCT,
            SymbolKind.TRAIT,
            SymbolKind.ENUM,
        }
    ),
    EdgeKind.IMPORTS: frozenset(SymbolKind),  # imports may target any definition
}


def build_graph(
    symbols_with_paths: Sequence[tuple[str, Symbol]],
    references: Sequence[tuple[str, Reference]],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes, node_keys, by_name = _build_nodes(symbols_with_paths)
    edges = _build_edges(references, node_keys, by_name)
    edges = _defines_edges(symbols_with_paths, node_keys) + edges
    return nodes, _dedupe(edges)


def _build_nodes(
    symbols_with_paths: Sequence[tuple[str, Symbol]],
) -> tuple[list[GraphNode], set[tuple[str, str]], dict[str, list[GraphNode]]]:
    nodes: list[GraphNode] = []
    keys: set[tuple[str, str]] = set()
    by_name: dict[str, list[GraphNode]] = {}

    def add(node: GraphNode) -> None:
        key = (node.path, node.qualified_name)
        if key in keys:
            return
        keys.add(key)
        nodes.append(node)
        by_name.setdefault(node.name, []).append(node)

    # Every indexed file gets a module node first, so its file-level
    # defines/imports edges always have a source — even an imports-only file.
    for path, _symbol in symbols_with_paths:
        add(
            GraphNode(
                path=path,
                qualified_name=_MODULE,
                name=_module_name(path),
                kind=SymbolKind.MODULE,
                start_line=1,
            )
        )
    for path, symbol in symbols_with_paths:
        if symbol.kind is SymbolKind.IMPORT:
            continue  # import statements are edges, not nodes
        add(
            GraphNode(
                path=path,
                qualified_name=symbol.qualified_name,
                name=symbol.name,
                kind=symbol.kind,
                start_line=symbol.start_line,
            )
        )
    return nodes, keys, by_name


def _defines_edges(
    symbols_with_paths: Sequence[tuple[str, Symbol]], node_keys: set[tuple[str, str]]
) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    for path, symbol in symbols_with_paths:
        if symbol.kind is SymbolKind.IMPORT:
            continue
        if (path, _MODULE) not in node_keys:
            continue
        edges.append(
            GraphEdge(
                src_path=path,
                src_qualified_name=_MODULE,
                dst_path=path,
                dst_qualified_name=symbol.qualified_name,
                kind=EdgeKind.DEFINES,
                line=symbol.start_line,
            )
        )
    return edges


def _build_edges(
    references: Sequence[tuple[str, Reference]],
    node_keys: set[tuple[str, str]],
    by_name: dict[str, list[GraphNode]],
) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    for path, ref in references:
        if (path, ref.from_qualified_name) not in node_keys:
            continue  # source scope was not emitted as a node (should not happen)
        for target in _resolve_targets(path, ref, by_name):
            edges.append(
                GraphEdge(
                    src_path=path,
                    src_qualified_name=ref.from_qualified_name,
                    dst_path=target.path,
                    dst_qualified_name=target.qualified_name,
                    kind=ref.kind,
                    line=ref.line,
                )
            )
    return edges


def _resolve_targets(
    path: str, ref: Reference, by_name: dict[str, list[GraphNode]]
) -> list[GraphNode]:
    allowed = _TARGET_KINDS[ref.kind]
    candidates = [n for n in by_name.get(ref.target_name, []) if n.kind in allowed]
    if not candidates:
        return []
    # Prefer a same-file definition; a local name shadows workspace-wide matches.
    same_file = [n for n in candidates if n.path == path]
    chosen = same_file or candidates
    # Never link a node to itself (e.g. direct recursion).
    chosen = [
        n for n in chosen if not (n.path == path and n.qualified_name == ref.from_qualified_name)
    ]
    return chosen[:_MAX_TARGETS]


def _dedupe(edges: list[GraphEdge]) -> list[GraphEdge]:
    seen: set[tuple[str, str, str, str, str]] = set()
    out: list[GraphEdge] = []
    for e in edges:
        key = (e.src_path, e.src_qualified_name, e.dst_path, e.dst_qualified_name, e.kind.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _module_name(path: str) -> str:
    # File stem without extension, so `import utils` can resolve to utils.py.
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
