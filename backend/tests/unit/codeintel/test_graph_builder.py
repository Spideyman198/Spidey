"""build_graph: name-based resolution of symbols + references into nodes/edges."""

from __future__ import annotations

from spidey.codeintel.application import build_graph
from spidey.codeintel.domain.models import EdgeKind, GraphEdge, Reference, Symbol, SymbolKind


def _sym(name: str, qn: str, kind: SymbolKind = SymbolKind.FUNCTION) -> Symbol:
    return Symbol(
        kind=kind,
        name=name,
        qualified_name=qn,
        parent=None,
        start_line=1,
        end_line=2,
        start_byte=0,
        end_byte=1,
    )


def _edge_set(edges: list[GraphEdge]) -> set[tuple[str, str, str, str, str]]:
    return {
        (e.src_path, e.src_qualified_name, e.dst_path, e.dst_qualified_name, e.kind.value)
        for e in edges
    }


class TestNodes:
    def test_module_node_and_symbol_nodes_created(self) -> None:
        nodes, _ = build_graph([("a.py", _sym("f", "f"))], [])
        kinds = {(n.qualified_name, n.kind) for n in nodes}
        assert ("<module>", SymbolKind.MODULE) in kinds
        assert ("f", SymbolKind.FUNCTION) in kinds

    def test_import_symbols_are_not_nodes(self) -> None:
        nodes, _ = build_graph([("a.py", _sym("import os", "import os", SymbolKind.IMPORT))], [])
        # Only the module node; the import statement itself is not a node.
        assert [n.qualified_name for n in nodes] == ["<module>"]


class TestEdges:
    def test_defines_edge_module_to_symbol(self) -> None:
        _, edges = build_graph([("a.py", _sym("f", "f"))], [])
        assert ("a.py", "<module>", "a.py", "f", "defines") in _edge_set(edges)

    def test_call_resolves_to_workspace_symbol(self) -> None:
        symbols = [("a.py", _sym("caller", "caller")), ("b.py", _sym("helper", "helper"))]
        refs = [
            (
                "a.py",
                Reference(
                    kind=EdgeKind.CALLS, from_qualified_name="caller", target_name="helper", line=4
                ),
            )
        ]
        _, edges = build_graph(symbols, refs)
        assert ("a.py", "caller", "b.py", "helper", "calls") in _edge_set(edges)

    def test_same_file_definition_shadows_cross_file(self) -> None:
        # 'helper' exists in both files; a call in a.py resolves to a.py's local.
        symbols = [
            ("a.py", _sym("caller", "caller")),
            ("a.py", _sym("helper", "helper")),
            ("b.py", _sym("helper", "helper")),
        ]
        refs = [
            (
                "a.py",
                Reference(
                    kind=EdgeKind.CALLS, from_qualified_name="caller", target_name="helper", line=4
                ),
            )
        ]
        _, edges = build_graph(symbols, refs)
        calls = [e for e in edges if e.kind is EdgeKind.CALLS]
        assert len(calls) == 1
        assert calls[0].dst_path == "a.py"

    def test_unresolved_external_call_is_dropped(self) -> None:
        symbols = [("a.py", _sym("caller", "caller"))]
        refs = [
            (
                "a.py",
                Reference(
                    kind=EdgeKind.CALLS,
                    from_qualified_name="caller",
                    target_name="requests",
                    line=4,
                ),
            )
        ]
        _, edges = build_graph(symbols, refs)
        assert not [e for e in edges if e.kind is EdgeKind.CALLS]

    def test_inherits_resolves_only_to_types(self) -> None:
        symbols = [
            ("a.py", _sym("Base", "Base", SymbolKind.CLASS)),
            ("a.py", _sym("Service", "Service", SymbolKind.CLASS)),
        ]
        refs = [
            (
                "a.py",
                Reference(
                    kind=EdgeKind.INHERITS,
                    from_qualified_name="Service",
                    target_name="Base",
                    line=1,
                ),
            )
        ]
        _, edges = build_graph(symbols, refs)
        assert ("a.py", "Service", "a.py", "Base", "inherits") in _edge_set(edges)

    def test_self_reference_is_not_edged(self) -> None:
        # Direct recursion: f calls f — no self-loop edge.
        symbols = [("a.py", _sym("f", "f"))]
        refs = [
            (
                "a.py",
                Reference(kind=EdgeKind.CALLS, from_qualified_name="f", target_name="f", line=2),
            )
        ]
        _, edges = build_graph(symbols, refs)
        assert not [e for e in edges if e.kind is EdgeKind.CALLS]

    def test_duplicate_edges_deduped(self) -> None:
        symbols = [("a.py", _sym("caller", "caller")), ("a.py", _sym("helper", "helper"))]
        refs = [
            (
                "a.py",
                Reference(
                    kind=EdgeKind.CALLS, from_qualified_name="caller", target_name="helper", line=4
                ),
            ),
            (
                "a.py",
                Reference(
                    kind=EdgeKind.CALLS, from_qualified_name="caller", target_name="helper", line=9
                ),
            ),
        ]
        _, edges = build_graph(symbols, refs)
        calls = [e for e in edges if e.kind is EdgeKind.CALLS]
        assert len(calls) == 1
