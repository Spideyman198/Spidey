"""Native file tools — reads and diff-based edits through SafeFileSystem (M8).

Security posture (docs/05 §2, docs/11): the filesystem stays native because
path containment and diff secret-scanning are *our* invariants. The workspace
comes from the trusted :class:`ToolContext`, never from arguments, so a call
cannot reach across workspaces. This provider holds **no file access of its
own** — all content operations live in the workspaces edit engine
(:mod:`spidey.workspaces.application.edits`), beside SafeFileSystem, which the
platform semgrep rule enforces (``spidey-agents-no-direct-file-io``).

``workspace.apply_edit`` is ``SideEffect.WRITE`` — the registry denies it
without a resolved human approval (M7 invariant). Its result *is* the unified
diff, grounding both the human approval and the reviewer loop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.agents.domain.tools import SideEffect, ToolResult, ToolSpec, TrustTier
from spidey.identity.domain.models import Role
from spidey.workspaces.application import apply_exact_edit, read_numbered
from spidey.workspaces.domain.paths import PathPolicyError, normalize_relative_path

if TYPE_CHECKING:
    from spidey.agents.domain.tools import ToolContext
    from spidey.workspaces.domain.ports import SafeFileSystem, WorkspaceStorage

READ_TOOL = "workspace.read_file"
EDIT_TOOL = "workspace.apply_edit"

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
        numbered = read_numbered(filesystem, path)
        if numbered is None:
            return ToolResult.error(f"no such file: {path}")
        return ToolResult.success(numbered)

    @staticmethod
    def _edit(filesystem: SafeFileSystem, path: str, arguments: dict[str, object]) -> ToolResult:
        old = arguments.get("old_string")
        new = arguments.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return ToolResult.error("'old_string' and 'new_string' must be strings")
        outcome = apply_exact_edit(filesystem, path=path, old_string=old, new_string=new)
        if outcome.denied is not None:
            return ToolResult.denied(outcome.denied)
        if outcome.error is not None:
            return ToolResult.error(outcome.error)
        return ToolResult.success(outcome.diff)
