"""Native file tools — reads and diff-based edits through SafeFileSystem (M8).

Security posture (docs/05 §2, docs/11): the filesystem stays native because
path containment and diff secret-scanning are *our* invariants. The workspace
comes from the trusted :class:`ToolContext`, never from arguments, so a call
cannot reach across workspaces; every path goes through ``SafeFileSystem``
(SEC-FS containment); and ``workspace.apply_edit`` is ``SideEffect.WRITE`` — the
registry denies it without a resolved human approval (M7 invariant). An edit
whose diff contains a credential shape is refused before anything is written.

Edits are exact-match replacements (``old_string`` → ``new_string``), which
makes them reviewable as unified diffs and atomic per file: the match must be
unique, and the returned content *is* the diff — grounding the reviewer loop.
"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

from spidey.agents.domain.tools import SideEffect, ToolResult, ToolSpec, TrustTier
from spidey.identity.domain.models import Role
from spidey.platform.security import describe_findings, scan_for_secrets
from spidey.workspaces.domain.paths import PathPolicyError, normalize_relative_path

if TYPE_CHECKING:
    from spidey.agents.domain.tools import ToolContext
    from spidey.workspaces.domain.ports import SafeFileSystem, WorkspaceStorage

READ_TOOL = "workspace.read_file"
EDIT_TOOL = "workspace.apply_edit"

_MAX_READ_CHARS = 100_000
_MAX_EDIT_BYTES = 1_000_000  # an edit target larger than this is suspicious
_READ_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 1024},
    },
    "required": ["path"],
    "additionalProperties": False,
}
_EDIT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "minLength": 1, "maxLength": 1024},
        "old_string": {
            "type": "string",
            "description": "Exact text to replace; empty string creates a new file.",
        },
        "new_string": {"type": "string"},
    },
    "required": ["path", "old_string", "new_string"],
    "additionalProperties": False,
}


class CodeEditProvider:
    """Native provider offering guarded file reads and approval-gated edits."""

    def __init__(self, *, storage: WorkspaceStorage) -> None:
        self._storage = storage

    @property
    def namespace(self) -> str:
        return "workspace"

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=READ_TOOL,
                description=(
                    "Read one file from the current workspace (UTF-8, "
                    "line-numbered). Paths are workspace-relative."
                ),
                input_schema=_READ_SCHEMA,
                side_effect=SideEffect.READ,
                trust_tier=TrustTier.TRUSTED,
                required_role=Role.VIEWER,
            ),
            ToolSpec(
                name=EDIT_TOOL,
                description=(
                    "Apply one exact-match edit to a workspace file: replace "
                    "old_string (must occur exactly once) with new_string, or "
                    "create a new file when old_string is empty. Returns the "
                    "unified diff. Requires human approval."
                ),
                input_schema=_EDIT_SCHEMA,
                side_effect=SideEffect.WRITE,
                trust_tier=TrustTier.TRUSTED,
                required_role=Role.DEVELOPER,
            ),
        ]

    async def invoke(
        self, name: str, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        if name not in (READ_TOOL, EDIT_TOOL):
            return ToolResult.error(f"unknown tool {name!r}")
        if context.workspace_id is None:
            return ToolResult.unavailable("no workspace is bound to this run")
        filesystem = self._storage.filesystem(context.workspace_id)
        path = arguments.get("path")
        if not isinstance(path, str):
            return ToolResult.error("'path' must be a string")
        try:
            # Layer-1 policy up front: a traversal *attempt* is a denial, not a
            # missing-file error (layer 2 inside SafeFileSystem catches links).
            normalize_relative_path(path)
            result = (
                self._read(filesystem, path)
                if name == READ_TOOL
                else self._edit(filesystem, path, arguments)
            )
        except PathPolicyError:
            return ToolResult.denied("path escapes the workspace root")
        except UnicodeDecodeError:
            return ToolResult.error("file is not valid UTF-8 text")
        return result

    @staticmethod
    def _read(filesystem: SafeFileSystem, path: str) -> ToolResult:
        if not filesystem.is_file(path):
            return ToolResult.error(f"no such file: {path}")
        text = filesystem.read_text(path)[:_MAX_READ_CHARS]
        numbered = "\n".join(
            f"{index:>6}\t{line}" for index, line in enumerate(text.splitlines(), start=1)
        )
        return ToolResult.success(numbered)

    @classmethod
    def _edit(
        cls, filesystem: SafeFileSystem, path: str, arguments: dict[str, object]
    ) -> ToolResult:
        resolved = cls._resolve_edit(filesystem, path, arguments)
        if isinstance(resolved, ToolResult):
            return resolved
        before, after = resolved

        diff = _unified_diff(path, before, after)
        # SEC-SECRETS: the diff is scanned *before* the write — a credential
        # never lands on disk, in an event, or in the model's context.
        findings = scan_for_secrets(diff)
        if findings:
            return ToolResult.denied(describe_findings(findings))

        filesystem.write_bytes(path, after.encode("utf-8"))
        return ToolResult.success(diff)

    @classmethod
    def _resolve_edit(
        cls, filesystem: SafeFileSystem, path: str, arguments: dict[str, object]
    ) -> tuple[str, str] | ToolResult:
        """Validate the requested edit and return (before, after) file contents,
        or the typed error explaining why the edit is impossible."""
        old = arguments.get("old_string")
        new = arguments.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return ToolResult.error("'old_string' and 'new_string' must be strings")
        if old == "":
            if filesystem.exists(path):
                return ToolResult.error(f"{path} already exists; pass old_string to edit it")
            return "", new
        return cls._resolve_replacement(filesystem, path, old, new)

    @staticmethod
    def _resolve_replacement(
        filesystem: SafeFileSystem, path: str, old: str, new: str
    ) -> tuple[str, str] | ToolResult:
        if not filesystem.is_file(path):
            return ToolResult.error(f"no such file: {path}")
        if filesystem.size(path) > _MAX_EDIT_BYTES:
            return ToolResult.error("file too large to edit")
        before = filesystem.read_text(path)
        occurrences = before.count(old)
        if occurrences == 0:
            return ToolResult.error("old_string not found in file")
        if occurrences > 1:
            return ToolResult.error(
                f"old_string occurs {occurrences} times; provide a unique match"
            )
        return before, before.replace(old, new, 1)


def _unified_diff(path: str, before: str, after: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(lines)
