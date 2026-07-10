"""Pure workspace-relative path validation (SEC-FS, layer 1).

This module rejects statically-detectable escape attempts — absolute paths,
drive letters, UNC prefixes, parent-directory traversal, and NUL bytes — before
any filesystem call. It is deliberately OS-agnostic and I/O-free so it can be
exhaustively unit-tested with attack strings. The second layer (symlink and
junction escape) requires real filesystem resolution and lives in the
``SafeFileSystem`` adapter; both layers must pass for access to be granted.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from spidey.platform.errors import SpideyError


class PathPolicyError(SpideyError):
    """A path violated the workspace containment policy."""

    status = 400
    title = "Invalid path"


def normalize_relative_path(raw: str) -> PurePosixPath:
    """Validate and normalize a workspace-relative path.

    Returns a clean forward-slashed relative path, or raises
    :class:`PathPolicyError`. Both ``/`` and ``\\`` are treated as separators so
    a Windows-shaped path cannot smuggle traversal past a POSIX check (or vice
    versa).
    """
    if not raw or not raw.strip():
        raise PathPolicyError("path must not be empty")
    if "\x00" in raw:
        raise PathPolicyError("path must not contain a NUL byte")

    # Treat backslash as a separator everywhere so validation is host-independent.
    unified = raw.replace("\\", "/")

    # Reject Windows drive letters (C:, c:\) and device/namespace prefixes.
    if len(unified) >= 2 and unified[1] == ":":  # noqa: PLR2004 — "X:" drive form
        raise PathPolicyError("drive-qualified paths are not permitted")

    # Reject absolute paths and UNC (leading slash, incl. // from \\server).
    if unified.startswith("/"):
        raise PathPolicyError("absolute paths are not permitted")

    pure = PurePosixPath(unified)
    for part in pure.parts:
        if part == "..":
            raise PathPolicyError("parent-directory traversal is not permitted")

    # Collapse '.' and empty segments; the result stays relative by construction.
    cleaned = PurePosixPath(*(part for part in pure.parts if part not in (".", "")))
    if not cleaned.parts:
        raise PathPolicyError("path resolves to the workspace root")
    return cleaned
