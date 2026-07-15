"""Tree-sitter symbol extraction and chunking, per language + resource bounds."""

from __future__ import annotations

import itertools

import pytest

from spidey.codeintel.domain.errors import ParseError
from spidey.codeintel.domain.models import Language, SymbolKind
from spidey.codeintel.infrastructure import TreeSitterParser


@pytest.fixture(scope="module")
def parser() -> TreeSitterParser:
    return TreeSitterParser()


def _kinds(parser: TreeSitterParser, lang: Language, src: bytes) -> dict[str, str]:
    unit = parser.parse(path=f"f.{lang.value}", language=lang, source=src)
    return {s.qualified_name: s.kind.value for s in unit.symbols}


def _pairs(parser: TreeSitterParser, lang: Language, src: bytes) -> set[tuple[str, str]]:
    unit = parser.parse(path=f"f.{lang.value}", language=lang, source=src)
    return {(s.qualified_name, s.kind.value) for s in unit.symbols}


class TestPython:
    SRC = (
        b"import os\n"
        b"from sys import path\n\n"
        b"def top():\n    return 1\n\n"
        b"class Widget:\n"
        b"    def method_a(self):\n        pass\n"
        b"    def method_b(self):\n        pass\n"
    )

    def test_symbols(self, parser: TreeSitterParser) -> None:
        kinds = _kinds(parser, Language.PYTHON, self.SRC)
        assert kinds["top"] == "function"
        assert kinds["Widget"] == "class"
        assert kinds["Widget.method_a"] == "method"  # nested function reclassified
        assert kinds["Widget.method_b"] == "method"

    def test_imports_captured(self, parser: TreeSitterParser) -> None:
        unit = parser.parse(path="f.py", language=Language.PYTHON, source=self.SRC)
        imports = [s for s in unit.symbols if s.kind is SymbolKind.IMPORT]
        assert len(imports) == 2
        assert imports[0].reference == "import os"

    def test_chunks_are_non_overlapping_and_ordered(self, parser: TreeSitterParser) -> None:
        unit = parser.parse(path="f.py", language=Language.PYTHON, source=self.SRC)
        chunks = unit.chunks
        # A module preamble chunk plus one per definition.
        assert chunks[0].header_path == "<module>"
        for earlier, later in itertools.pairwise(chunks):
            assert earlier.start_byte <= later.start_byte
            assert earlier.end_byte <= later.start_byte  # non-overlapping


class TestOtherLanguages:
    @pytest.mark.parametrize(
        ("lang", "src", "expected"),
        [
            (
                Language.GO,
                b'package m\nimport "fmt"\ntype S interface { A() }\n'
                b"type C struct { r int }\nfunc (c C) A() {}\nfunc main() {}\n",
                {"S": "interface", "C": "struct", "A": "method", "main": "function"},
            ),
            (
                Language.RUST,
                b"use std::io;\nstruct P { x: i32 }\n"
                b"impl P { fn new() -> P { P{x:0} } }\nfn free() {}\n",
                {"P": "struct", "P.new": "method", "free": "function"},
            ),
            (
                Language.TYPESCRIPT,
                b'import {a} from "x";\ninterface I { n: number }\n'
                b"class C { m() {} }\nfunction f() {}\n",
                {"I": "interface", "C": "class", "C.m": "method", "f": "function"},
            ),
            (
                Language.JAVA,
                b"import java.util.List;\nclass Svc { void run() {} }\n"
                b"interface I { void go(); }\n",
                {"Svc": "class", "Svc.run": "method", "I": "interface", "I.go": "method"},
            ),
            (
                Language.JAVASCRIPT,
                b'import x from "y";\nfunction f(){}\nclass C { m(){} }\n',
                {"f": "function", "C": "class", "C.m": "method"},
            ),
        ],
    )
    def test_symbol_kinds(
        self, parser: TreeSitterParser, lang: Language, src: bytes, expected: dict[str, str]
    ) -> None:
        # Membership check (not dict-keyed): a name may legitimately carry two
        # kinds, e.g. Rust `struct P` and `impl P` both named "P".
        pairs = _pairs(parser, lang, src)
        for qualified, kind in expected.items():
            assert (qualified, kind) in pairs, (
                f"{lang.value}: missing {(qualified, kind)} in {pairs}"
            )


class TestResourceBounds:
    def test_oversized_source_rejected(self, parser: TreeSitterParser) -> None:
        big = b"x = 1\n" * (2 * 1024 * 1024)  # over the 8 MiB cap
        with pytest.raises(ParseError):
            parser.parse(path="big.py", language=Language.PYTHON, source=big)

    def test_malformed_source_does_not_crash(self, parser: TreeSitterParser) -> None:
        # Tree-sitter is error-tolerant; a broken file still parses (with error
        # nodes) and yields whatever symbols it can, never raising.
        unit = parser.parse(
            path="broken.py",
            language=Language.PYTHON,
            source=b"def ok():\n    pass\ndef broken(:\n",
        )
        assert any(s.name == "ok" for s in unit.symbols)

    def test_empty_file(self, parser: TreeSitterParser) -> None:
        unit = parser.parse(path="empty.py", language=Language.PYTHON, source=b"")
        assert unit.symbols == []
