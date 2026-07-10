"""File-manifest construction: content hashing, binary detection, ignore rules.

The manifest is the substrate for incremental indexing (FR-1.3): each entry's
SHA-256 lets a later sync skip unchanged files. Ignore handling composes the
repository's ``.gitignore`` with always-excluded VCS internals; binary and
oversized files are inventoried but flagged non-indexable so parsing (M3) can
skip them cheaply.
"""

from __future__ import annotations

import contextlib
import hashlib
from typing import TYPE_CHECKING

import pathspec

from spidey.workspaces.domain.models import FileManifestEntry

if TYPE_CHECKING:
    from spidey.workspaces.domain.ports import SafeFileSystem

# Directories whose contents are never indexed regardless of .gitignore.
_ALWAYS_IGNORED_DIRS = (".git/",)
_BINARY_SNIFF_BYTES = 8192


def _is_binary(sample: bytes) -> bool:
    # A NUL byte is the classic, cheap, high-precision binary signal.
    return b"\x00" in sample


def _load_gitignore(fs: SafeFileSystem) -> pathspec.GitIgnoreSpec:
    patterns: list[str] = list(_ALWAYS_IGNORED_DIRS)
    if fs.exists(".gitignore") and fs.is_file(".gitignore"):
        # A malformed .gitignore simply contributes no extra patterns.
        with contextlib.suppress(UnicodeDecodeError, OSError):
            patterns.extend(fs.read_text(".gitignore").splitlines())
    return pathspec.GitIgnoreSpec.from_lines(patterns)


def build_manifest(fs: SafeFileSystem, *, max_file_bytes: int) -> list[FileManifestEntry]:
    """Walk the workspace and produce a deterministic, path-sorted manifest."""
    spec = _load_gitignore(fs)
    entries: list[FileManifestEntry] = []

    for file in fs.walk_files():
        if spec.match_file(file.path):
            continue
        digest = hashlib.sha256()
        oversized = file.size_bytes > max_file_bytes
        binary = False
        if not oversized:
            data = fs.read_bytes(file.path)
            digest.update(data)
            binary = _is_binary(data[:_BINARY_SNIFF_BYTES])
        else:
            # Hash the identity (path+size) rather than reading a huge blob; the
            # file is inventoried but never indexed, so content hashing is moot.
            digest.update(f"{file.path}:{file.size_bytes}".encode())

        entries.append(
            FileManifestEntry(
                path=file.path,
                sha256=digest.hexdigest(),
                size_bytes=file.size_bytes,
                is_binary=binary,
                indexable=not oversized and not binary,
            )
        )

    entries.sort(key=lambda entry: entry.path)
    return entries
