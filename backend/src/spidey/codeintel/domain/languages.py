"""Language registry: file-extension mapping and per-language extraction specs.

This is the pluggable grammar layer (FR-2.1): enabling a language means adding
its extension mapping and a :class:`LanguageSpec` describing which Tree-sitter
node types map to which symbol kinds, and how to read a definition's name.
Grammars themselves come from the ABI-matched language pack (ADR note in
docs/06); this module decides which are *enabled* and how their trees are read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from spidey.codeintel.domain.models import Language, SymbolKind

# File extension → enabled language.
EXTENSION_LANGUAGE: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".pyi": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
    ".mjs": Language.JAVASCRIPT,
    ".cjs": Language.JAVASCRIPT,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT,
    ".go": Language.GO,
    ".java": Language.JAVA,
    ".rs": Language.RUST,
}


def language_for_path(path: str) -> Language | None:
    return EXTENSION_LANGUAGE.get(PurePosixPath(path).suffix.lower())


@dataclass(frozen=True)
class LanguageSpec:
    """How to read one language's tree.

    ``definitions`` maps a Tree-sitter node type to the symbol kind it yields.
    ``method_container_kinds`` are the symbol kinds whose direct function/method
    children should be reclassified as methods. ``import_nodes`` are node types
    treated as imports (their full text becomes the reference). ``name_field``
    is the field name holding the identifier (default ``name``); a few node
    types need a custom resolver, handled in the parser.
    """

    definitions: dict[str, SymbolKind]
    import_nodes: frozenset[str]
    method_container_kinds: frozenset[SymbolKind] = field(
        default_factory=lambda: frozenset({SymbolKind.CLASS, SymbolKind.STRUCT, SymbolKind.TRAIT})
    )


_PYTHON = LanguageSpec(
    definitions={
        "class_definition": SymbolKind.CLASS,
        "function_definition": SymbolKind.FUNCTION,
    },
    import_nodes=frozenset({"import_statement", "import_from_statement"}),
)

_JS = LanguageSpec(
    definitions={
        "class_declaration": SymbolKind.CLASS,
        "function_declaration": SymbolKind.FUNCTION,
        "generator_function_declaration": SymbolKind.FUNCTION,
        "method_definition": SymbolKind.METHOD,
    },
    import_nodes=frozenset({"import_statement"}),
)

_TS = LanguageSpec(
    definitions={
        "class_declaration": SymbolKind.CLASS,
        "abstract_class_declaration": SymbolKind.CLASS,
        "interface_declaration": SymbolKind.INTERFACE,
        "enum_declaration": SymbolKind.ENUM,
        "function_declaration": SymbolKind.FUNCTION,
        "method_definition": SymbolKind.METHOD,
    },
    import_nodes=frozenset({"import_statement"}),
)

_GO = LanguageSpec(
    definitions={
        "function_declaration": SymbolKind.FUNCTION,
        "method_declaration": SymbolKind.METHOD,
        "type_spec": SymbolKind.STRUCT,  # refined to interface/struct in the parser
    },
    import_nodes=frozenset({"import_declaration"}),
)

_JAVA = LanguageSpec(
    definitions={
        "class_declaration": SymbolKind.CLASS,
        "interface_declaration": SymbolKind.INTERFACE,
        "enum_declaration": SymbolKind.ENUM,
        "record_declaration": SymbolKind.CLASS,
        "method_declaration": SymbolKind.METHOD,
        "constructor_declaration": SymbolKind.METHOD,
    },
    import_nodes=frozenset({"import_declaration"}),
)

_RUST = LanguageSpec(
    definitions={
        "function_item": SymbolKind.FUNCTION,
        "struct_item": SymbolKind.STRUCT,
        "enum_item": SymbolKind.ENUM,
        "trait_item": SymbolKind.TRAIT,
        "impl_item": SymbolKind.CLASS,  # impl blocks group methods
        "mod_item": SymbolKind.CLASS,
    },
    import_nodes=frozenset({"use_declaration"}),
)

LANGUAGE_SPECS: dict[Language, LanguageSpec] = {
    Language.PYTHON: _PYTHON,
    Language.JAVASCRIPT: _JS,
    Language.TYPESCRIPT: _TS,
    Language.GO: _GO,
    Language.JAVA: _JAVA,
    Language.RUST: _RUST,
}
