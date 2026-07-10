"""Manifest construction: hashing, binary detection, gitignore, size caps."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from spidey.workspaces.application import build_manifest
from spidey.workspaces.infrastructure import GuardedFileSystem

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def fs(tmp_path: Path) -> GuardedFileSystem:
    root = tmp_path / "ws"
    root.mkdir()
    # write_bytes (not write_text): avoid the platform newline translation that
    # would make content hashes non-deterministic across OSes.
    (root / "main.py").write_bytes(b"print('hi')\n")
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x01\x02binary")
    (root / "sub").mkdir()
    (root / "sub" / "util.py").write_bytes(b"x = 1\n")
    return GuardedFileSystem(root)


class TestManifest:
    def test_hashes_and_sorts(self, fs: GuardedFileSystem) -> None:
        entries = build_manifest(fs, max_file_bytes=1_000_000)
        paths = [e.path for e in entries]
        assert paths == sorted(paths)
        by_path = {e.path: e for e in entries}
        assert by_path["main.py"].sha256 == hashlib.sha256(b"print('hi')\n").hexdigest()

    def test_binary_detected_and_not_indexable(self, fs: GuardedFileSystem) -> None:
        entry = next(
            e for e in build_manifest(fs, max_file_bytes=1_000_000) if e.path == "logo.png"
        )
        assert entry.is_binary
        assert not entry.indexable

    def test_text_is_indexable(self, fs: GuardedFileSystem) -> None:
        entry = next(e for e in build_manifest(fs, max_file_bytes=1_000_000) if e.path == "main.py")
        assert not entry.is_binary
        assert entry.indexable

    def test_oversized_file_inventoried_not_indexable(self, fs: GuardedFileSystem) -> None:
        entries = build_manifest(fs, max_file_bytes=5)  # everything is "oversized"
        assert all(not e.indexable for e in entries)
        # Still inventoried with sizes recorded.
        assert {e.path for e in entries} == {"main.py", "logo.png", "sub/util.py"}


class TestGitignore:
    def test_gitignore_patterns_excluded(self, tmp_path: Path) -> None:
        root = tmp_path / "ws"
        root.mkdir()
        (root / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")
        (root / "app.py").write_text("code", encoding="utf-8")
        (root / "debug.log").write_text("noise", encoding="utf-8")
        (root / "build").mkdir()
        (root / "build" / "out.bin").write_text("artifact", encoding="utf-8")

        paths = {e.path for e in build_manifest(GuardedFileSystem(root), max_file_bytes=1_000_000)}
        assert "app.py" in paths
        assert ".gitignore" in paths
        assert "debug.log" not in paths
        assert "build/out.bin" not in paths

    def test_git_internals_always_excluded(self, tmp_path: Path) -> None:
        root = tmp_path / "ws"
        (root / ".git").mkdir(parents=True)
        (root / ".git" / "config").write_text("[core]", encoding="utf-8")
        (root / "readme.md").write_text("hi", encoding="utf-8")

        paths = {e.path for e in build_manifest(GuardedFileSystem(root), max_file_bytes=1_000_000)}
        assert paths == {"readme.md"}
