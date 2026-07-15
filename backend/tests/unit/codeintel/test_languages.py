"""Language registry: extension mapping (FR-2.1)."""

from __future__ import annotations

import pytest

from spidey.codeintel.domain.languages import language_for_path
from spidey.codeintel.domain.models import Language


class TestExtensionMapping:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("src/main.py", Language.PYTHON),
            ("a/b/types.pyi", Language.PYTHON),
            ("app.js", Language.JAVASCRIPT),
            ("comp.jsx", Language.JAVASCRIPT),
            ("mod.mjs", Language.JAVASCRIPT),
            ("index.ts", Language.TYPESCRIPT),
            ("view.tsx", Language.TYPESCRIPT),
            ("server.go", Language.GO),
            ("Main.java", Language.JAVA),
            ("lib.rs", Language.RUST),
        ],
    )
    def test_known_extensions(self, path: str, expected: Language) -> None:
        assert language_for_path(path) is expected

    @pytest.mark.parametrize(
        "path", ["README.md", "data.json", "image.png", "Makefile", "script.sh", "noext"]
    )
    def test_unsupported_returns_none(self, path: str) -> None:
        assert language_for_path(path) is None

    def test_case_insensitive(self) -> None:
        assert language_for_path("MAIN.PY") is Language.PYTHON
