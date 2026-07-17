"""CodeEditProvider: guarded reads, exact-match edits, secret blocks, and the
registry approval gate over the write tool — all on a real GuardedFileSystem."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from spidey.agents.application import ToolRegistry
from spidey.agents.domain import ToolContext, ToolOutcome
from spidey.agents.domain.runs import Approval, ApprovalStatus
from spidey.agents.infrastructure import CodeEditProvider
from spidey.agents.infrastructure.code_edit import EDIT_TOOL, READ_TOOL
from spidey.identity.domain.models import Role
from spidey.workspaces.infrastructure.filesystem import GuardedFileSystem


class _Storage:
    def __init__(self, root: Path) -> None:
        self._root = root

    def filesystem(self, workspace_id: uuid.UUID) -> GuardedFileSystem:
        return GuardedFileSystem(self._root)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    return root


def _provider(root: Path) -> CodeEditProvider:
    return CodeEditProvider(storage=_Storage(root))  # type: ignore[arg-type]


def _context(role: Role = Role.DEVELOPER) -> ToolContext:
    return ToolContext(
        actor_user_id=uuid.uuid4(),
        role=role,
        run_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
    )


class TestReadFile:
    async def test_reads_with_line_numbers(self, tmp_path: Path) -> None:
        provider = _provider(_workspace(tmp_path))
        result = await provider.invoke(READ_TOOL, {"path": "app.py"}, _context())
        assert result.ok
        assert "1\tdef main():" in result.content

    async def test_missing_file_is_an_error(self, tmp_path: Path) -> None:
        provider = _provider(_workspace(tmp_path))
        result = await provider.invoke(READ_TOOL, {"path": "nope.py"}, _context())
        assert result.outcome is ToolOutcome.ERROR

    async def test_traversal_is_denied(self, tmp_path: Path) -> None:
        provider = _provider(_workspace(tmp_path))
        result = await provider.invoke(READ_TOOL, {"path": "../outside.txt"}, _context())
        assert result.outcome is ToolOutcome.DENIED


class TestApplyEdit:
    async def test_unique_match_is_replaced_and_diff_returned(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        provider = _provider(root)
        result = await provider.invoke(
            EDIT_TOOL,
            {"path": "app.py", "old_string": "return 1", "new_string": "return 2"},
            _context(),
        )
        assert result.ok
        assert "-    return 1" in result.content
        assert "+    return 2" in result.content
        assert "return 2" in (root / "app.py").read_text(encoding="utf-8")

    async def test_empty_old_string_creates_a_new_file(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        provider = _provider(root)
        result = await provider.invoke(
            EDIT_TOOL,
            {"path": "pkg/util.py", "old_string": "", "new_string": "x = 1\n"},
            _context(),
        )
        assert result.ok
        assert (root / "pkg" / "util.py").read_text(encoding="utf-8") == "x = 1\n"

    async def test_creating_an_existing_file_is_an_error(self, tmp_path: Path) -> None:
        provider = _provider(_workspace(tmp_path))
        result = await provider.invoke(
            EDIT_TOOL, {"path": "app.py", "old_string": "", "new_string": "y"}, _context()
        )
        assert result.outcome is ToolOutcome.ERROR

    async def test_ambiguous_match_is_rejected(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        (root / "app.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
        provider = _provider(root)
        result = await provider.invoke(
            EDIT_TOOL,
            {"path": "app.py", "old_string": "x = 1", "new_string": "x = 2"},
            _context(),
        )
        assert result.outcome is ToolOutcome.ERROR
        assert "2 times" in result.content

    async def test_missing_match_is_rejected(self, tmp_path: Path) -> None:
        provider = _provider(_workspace(tmp_path))
        result = await provider.invoke(
            EDIT_TOOL,
            {"path": "app.py", "old_string": "nonexistent", "new_string": "z"},
            _context(),
        )
        assert result.outcome is ToolOutcome.ERROR

    async def test_secret_in_edit_is_blocked_before_write(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        provider = _provider(root)
        result = await provider.invoke(
            EDIT_TOOL,
            {
                "path": "config.py",
                "old_string": "",
                "new_string": 'KEY = "sk-ant-plantedsecret1234"\n',
            },
            _context(),
        )
        assert result.outcome is ToolOutcome.DENIED
        assert "sk-ant" not in result.content  # refusal never echoes the secret
        assert not (root / "config.py").exists()  # nothing written

    async def test_write_through_traversal_path_is_denied(self, tmp_path: Path) -> None:
        provider = _provider(_workspace(tmp_path))
        result = await provider.invoke(
            EDIT_TOOL,
            {"path": "../evil.py", "old_string": "", "new_string": "x"},
            _context(),
        )
        assert result.outcome is ToolOutcome.DENIED
        assert not (tmp_path / "evil.py").exists()


class TestRegistryGate:
    """The write tool rides the M7 approval invariant end to end."""

    async def test_edit_denied_without_approval(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        registry = ToolRegistry(providers=[_provider(root)])
        result = await registry.invoke(
            name=EDIT_TOOL,
            arguments={"path": "app.py", "old_string": "return 1", "new_string": "return 2"},
            context=_context(),
        )
        assert result.outcome is ToolOutcome.DENIED
        assert "return 1" in (root / "app.py").read_text(encoding="utf-8")  # untouched

    async def test_edit_runs_with_matching_approval(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        registry = ToolRegistry(providers=[_provider(root)])
        context = _context()
        approval = Approval(
            id=uuid.uuid4(),
            run_id=context.run_id or uuid.uuid4(),
            tool=EDIT_TOOL,
            side_effect="write",
            arguments_preview="{}",
            status=ApprovalStatus.APPROVED,
            requested_at=datetime.now(tz=UTC),
        )
        result = await registry.invoke(
            name=EDIT_TOOL,
            arguments={"path": "app.py", "old_string": "return 1", "new_string": "return 2"},
            context=context,
            approval=approval,
        )
        assert result.ok
        assert "return 2" in (root / "app.py").read_text(encoding="utf-8")

    async def test_viewer_role_cannot_edit_even_with_approval(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        registry = ToolRegistry(providers=[_provider(root)])
        context = _context(Role.VIEWER)
        approval = Approval(
            id=uuid.uuid4(),
            run_id=context.run_id or uuid.uuid4(),
            tool=EDIT_TOOL,
            side_effect="write",
            arguments_preview="{}",
            status=ApprovalStatus.APPROVED,
            requested_at=datetime.now(tz=UTC),
        )
        result = await registry.invoke(
            name=EDIT_TOOL,
            arguments={"path": "app.py", "old_string": "return 1", "new_string": "return 2"},
            context=context,
            approval=approval,
        )
        assert result.outcome is ToolOutcome.DENIED  # RBAC precedes the approval gate
