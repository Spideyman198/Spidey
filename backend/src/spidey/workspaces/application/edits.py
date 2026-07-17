"""Exact-match edit engine over SafeFileSystem (M8).

This is the only code that touches file contents for agent edits, and it lives
in the workspaces context on purpose: path containment and diff secret-scanning
are *this* context's security invariants (docs/05 §2), and the platform semgrep
rule bans direct file access anywhere in ``agents``/``codeintel`` — agent code
calls these functions, never the filesystem.

Edits are exact-match replacements (``old_string`` → ``new_string``; empty
``old_string`` creates a new file). The match must be unique, the computed
unified diff **is** the result artifact, and a credential-shaped diff is refused
before anything is written (SEC-SECRETS).
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from spidey.platform.security import describe_findings, scan_for_secrets

if TYPE_CHECKING:
    from spidey.workspaces.domain.ports import SafeFileSystem

MAX_READ_CHARS = 100_000
MAX_EDIT_BYTES = 1_000_000  # an edit target larger than this is suspicious


class EditOutcome(BaseModel):
    """Typed result of one edit attempt. Exactly one field is populated."""

    model_config = ConfigDict(frozen=True)

    diff: str = ""
    error: str | None = None  # the edit is impossible (bad match, missing file…)
    denied: str | None = None  # the edit is refused by policy (secret detected)

    @property
    def ok(self) -> bool:
        return self.error is None and self.denied is None


def read_numbered(filesystem: SafeFileSystem, path: str) -> str | None:
    """A file's text with 1-indexed line numbers, or None when it is not a
    regular contained file. Raises ``PathPolicyError`` on containment breaches
    and ``UnicodeDecodeError`` on non-text content."""
    if not filesystem.is_file(path):
        return None
    text = filesystem.read_text(path)[:MAX_READ_CHARS]
    return "\n".join(f"{index:>6}\t{line}" for index, line in enumerate(text.splitlines(), start=1))


def apply_exact_edit(
    filesystem: SafeFileSystem, *, path: str, old_string: str, new_string: str
) -> EditOutcome:
    """Apply one unique exact-match replacement (or create a new file) and
    return the unified diff — unless the diff carries a secret, in which case
    nothing is written and the refusal names only the kind and line."""
    resolved = _resolve(filesystem, path, old_string, new_string)
    if isinstance(resolved, EditOutcome):
        return resolved
    before, after = resolved

    diff = _unified_diff(path, before, after)
    # SEC-SECRETS: the diff is scanned *before* the write — a credential never
    # lands on disk, in an event, or in the model's context.
    findings = scan_for_secrets(diff)
    if findings:
        return EditOutcome(denied=describe_findings(findings))

    filesystem.write_bytes(path, after.encode("utf-8"))
    return EditOutcome(diff=diff)


def _resolve(
    filesystem: SafeFileSystem, path: str, old: str, new: str
) -> tuple[str, str] | EditOutcome:
    """Validate the request and return (before, after) contents, or the typed
    error explaining why the edit is impossible."""
    if old == "":
        if filesystem.exists(path):
            return EditOutcome(error=f"{path} already exists; pass old_string to edit it")
        return "", new
    return _resolve_replacement(filesystem, path, old, new)


def _resolve_replacement(
    filesystem: SafeFileSystem, path: str, old: str, new: str
) -> tuple[str, str] | EditOutcome:
    if not filesystem.is_file(path):
        return EditOutcome(error=f"no such file: {path}")
    if filesystem.size(path) > MAX_EDIT_BYTES:
        return EditOutcome(error="file too large to edit")
    before = filesystem.read_text(path)
    occurrences = before.count(old)
    if occurrences == 0:
        return EditOutcome(error="old_string not found in file")
    if occurrences > 1:
        return EditOutcome(error=f"old_string occurs {occurrences} times; provide a unique match")
    return before, before.replace(old, new, 1)


def _unified_diff(path: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(lines)
