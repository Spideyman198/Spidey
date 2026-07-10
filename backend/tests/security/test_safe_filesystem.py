"""Attack-shaped tests for SafeFileSystem containment (SEC-FS).

These assert that no traversal, absolute path, drive/UNC prefix, symlink, or
(on Windows) junction can read or write outside the workspace root. They are
the executable form of the milestone's security promise and must fail loudly if
containment ever weakens.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from spidey.workspaces.domain.paths import (
    PathPolicyError,
    normalize_relative_path,
)
from spidey.workspaces.infrastructure import GuardedFileSystem


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[GuardedFileSystem, Path, Path]:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "keep.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("TOP SECRET", encoding="utf-8")
    return GuardedFileSystem(root), root, outside


class TestPurePolicy:
    @pytest.mark.parametrize(
        "attack",
        [
            "../secret.txt",
            "../../etc/passwd",
            "a/../../b",
            "/etc/passwd",
            "/absolute",
            "C:/Windows/System32/drivers/etc/hosts",
            "c:\\windows\\system32",
            "\\\\server\\share\\file",
            "..\\..\\secret.txt",
            "foo/../../bar",
            "with\x00nul",
            "",
            "   ",
        ],
    )
    def test_policy_rejects_escape_shapes(self, attack: str) -> None:
        with pytest.raises(PathPolicyError):
            normalize_relative_path(attack)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("a/b/c.txt", "a/b/c.txt"),
            ("./a/./b", "a/b"),
            ("dir\\file.txt", "dir/file.txt"),  # backslash normalized to slash
            ("a//b", "a/b"),
        ],
    )
    def test_policy_accepts_and_normalizes(self, raw: str, expected: str) -> None:
        assert normalize_relative_path(raw).as_posix() == expected


class TestReadContainment:
    def test_reads_contained_file(self, workspace: tuple[GuardedFileSystem, Path, Path]) -> None:
        fs, _, _ = workspace
        assert fs.read_text("keep.txt") == "inside"

    @pytest.mark.parametrize(
        "attack",
        [
            "../secret.txt",
            "../../secret.txt",
            "..\\secret.txt",
            "/etc/passwd",
            "a/../../secret.txt",
        ],
    )
    def test_traversal_reads_are_blocked(
        self, workspace: tuple[GuardedFileSystem, Path, Path], attack: str
    ) -> None:
        fs, _, _ = workspace
        with pytest.raises(PathPolicyError):
            fs.read_bytes(attack)


class TestSymlinkEscape:
    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink test")
    def test_symlink_out_of_root_is_rejected(
        self, workspace: tuple[GuardedFileSystem, Path, Path]
    ) -> None:
        fs, root, outside = workspace
        (root / "escape").symlink_to(outside)
        with pytest.raises(PathPolicyError):
            fs.read_text("escape")

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink test")
    def test_symlinked_dir_is_not_walked(
        self, workspace: tuple[GuardedFileSystem, Path, Path]
    ) -> None:
        fs, root, _ = workspace
        target = root.parent / "external_dir"
        target.mkdir()
        (target / "leaked.txt").write_text("leak", encoding="utf-8")
        (root / "linkdir").symlink_to(target, target_is_directory=True)
        walked = {f.path for f in fs.walk_files()}
        assert "linkdir/leaked.txt" not in walked
        assert "keep.txt" in walked

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows junction test")
    def test_ntfs_junction_out_of_root_is_rejected(
        self, workspace: tuple[GuardedFileSystem, Path, Path]
    ) -> None:
        import subprocess

        fs, root, _ = workspace
        external = root.parent / "external_dir"
        external.mkdir()
        (external / "leaked.txt").write_text("leak", encoding="utf-8")
        junction = root / "junction"
        # mklink /J creates an NTFS junction (reparse point) without admin.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("could not create NTFS junction in this environment")
        with pytest.raises(PathPolicyError):
            fs.read_text("junction/leaked.txt")
        assert "junction/leaked.txt" not in {f.path for f in fs.walk_files()}


class TestWriteContainment:
    def test_writes_stay_inside(self, workspace: tuple[GuardedFileSystem, Path, Path]) -> None:
        fs, root, _ = workspace
        fs.write_bytes("nested/new.txt", b"data")
        assert (root / "nested" / "new.txt").read_bytes() == b"data"

    def test_write_traversal_is_blocked(
        self, workspace: tuple[GuardedFileSystem, Path, Path]
    ) -> None:
        fs, _, outside = workspace
        with pytest.raises(PathPolicyError):
            fs.write_bytes("../secret.txt", b"overwritten")
        assert outside.read_text(encoding="utf-8") == "TOP SECRET"


class TestWalkAndSize:
    def test_walk_lists_only_contained_regular_files(
        self, workspace: tuple[GuardedFileSystem, Path, Path]
    ) -> None:
        fs, root, _ = workspace
        (root / "sub").mkdir()
        (root / "sub" / "b.txt").write_text("bb", encoding="utf-8")
        paths = {f.path for f in fs.walk_files()}
        assert paths == {"keep.txt", "sub/b.txt"}

    def test_total_size_sums_contained_files(
        self, workspace: tuple[GuardedFileSystem, Path, Path]
    ) -> None:
        fs, _, _ = workspace
        assert fs.total_size() == len("inside")


class TestConstruction:
    def test_missing_root_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            GuardedFileSystem(tmp_path / "does-not-exist")

    def test_file_as_root_is_rejected(self, tmp_path: Path) -> None:
        target = tmp_path / "afile"
        target.write_text("x", encoding="utf-8")
        with pytest.raises((PathPolicyError, NotADirectoryError)):
            GuardedFileSystem(target)
