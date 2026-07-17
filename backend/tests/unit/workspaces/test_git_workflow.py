"""GitWorkflowService: branch-per-run isolation, secret-gated atomic commits."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import ClassVar

from git import Repo

from spidey.workspaces.application import GitWorkflowService, branch_for_run
from spidey.workspaces.infrastructure.git_provider import GitPythonProvider


class _Settings:
    allowed_git_hosts: ClassVar[list[str]] = ["github.com"]


class _Storage:
    """path_for is all the workflow needs from WorkspaceStorage."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def path_for(self, workspace_id: uuid.UUID) -> str:
        return str(self._root)


def _service(root: Path) -> GitWorkflowService:
    return GitWorkflowService(
        git=GitPythonProvider(_Settings()),  # type: ignore[arg-type]
        storage=_Storage(root),  # type: ignore[arg-type]
    )


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    return root


class TestPrepareRunBranch:
    async def test_plain_tree_becomes_repo_on_isolated_branch(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        run_id, ws_id = uuid.uuid4(), uuid.uuid4()
        prepared = await _service(root).prepare_run_branch(workspace_id=ws_id, run_id=run_id)

        assert prepared.branch == branch_for_run(run_id) == f"spidey/run-{run_id}"
        assert prepared.base_commit is not None  # baseline committed
        repo = Repo(root)
        try:
            assert repo.active_branch.name == prepared.branch
            assert str(repo.head.commit.message).startswith("chore(spidey): run baseline")
        finally:
            repo.close()

    async def test_prepare_is_idempotent_across_resume(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        service = _service(root)
        run_id, ws_id = uuid.uuid4(), uuid.uuid4()
        first = await service.prepare_run_branch(workspace_id=ws_id, run_id=run_id)
        second = await service.prepare_run_branch(workspace_id=ws_id, run_id=run_id)
        assert first.branch == second.branch
        assert first.base_commit == second.base_commit  # clean tree → same baseline


class TestCommitStep:
    async def test_commits_step_with_conventional_message(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        service = _service(root)
        run_id, ws_id = uuid.uuid4(), uuid.uuid4()
        await service.prepare_run_branch(workspace_id=ws_id, run_id=run_id)

        (root / "app.py").write_text("def main():\n    return 2\n", encoding="utf-8")
        outcome = await service.commit_step(
            workspace_id=ws_id, run_id=run_id, step_index=0, summary="bump return value"
        )
        assert outcome.committed
        assert not outcome.blocked
        repo = Repo(root)
        try:
            message = str(repo.head.commit.message)
            assert message.startswith("feat(run): bump return value")
            assert f"Run: {run_id}" in message
            assert "Step: 0" in message
        finally:
            repo.close()

    async def test_secret_in_diff_blocks_the_commit(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        service = _service(root)
        run_id, ws_id = uuid.uuid4(), uuid.uuid4()
        prepared = await service.prepare_run_branch(workspace_id=ws_id, run_id=run_id)

        (root / "config.py").write_text(
            'API_KEY = "sk-ant-plantedsecret123456"\n', encoding="utf-8"
        )
        outcome = await service.commit_step(
            workspace_id=ws_id, run_id=run_id, step_index=1, summary="add config"
        )
        assert not outcome.committed
        assert [f.kind for f in outcome.blocked] == ["anthropic api key"]
        # Nothing landed: HEAD is still the baseline.
        repo = Repo(root)
        try:
            assert repo.head.commit.hexsha == prepared.base_commit
        finally:
            repo.close()

    async def test_clean_tree_commits_nothing(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        service = _service(root)
        run_id, ws_id = uuid.uuid4(), uuid.uuid4()
        await service.prepare_run_branch(workspace_id=ws_id, run_id=run_id)
        outcome = await service.commit_step(
            workspace_id=ws_id, run_id=run_id, step_index=0, summary="noop"
        )
        assert not outcome.committed
        assert not outcome.blocked


class TestRunDiff:
    async def test_cumulative_diff_against_base(self, tmp_path: Path) -> None:
        root = _workspace(tmp_path)
        service = _service(root)
        run_id, ws_id = uuid.uuid4(), uuid.uuid4()
        prepared = await service.prepare_run_branch(workspace_id=ws_id, run_id=run_id)

        (root / "app.py").write_text("def main():\n    return 2\n", encoding="utf-8")
        await service.commit_step(
            workspace_id=ws_id, run_id=run_id, step_index=0, summary="step one"
        )
        (root / "new.py").write_text("x = 1\n", encoding="utf-8")  # uncommitted

        diff = await service.run_diff(workspace_id=ws_id, base=prepared.base_commit)
        assert "+    return 2" in diff  # committed step included
        assert "new.py" in diff  # working tree included
