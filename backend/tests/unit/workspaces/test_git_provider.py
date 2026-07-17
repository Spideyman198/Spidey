"""GitProvider: token injection, local HEAD reading, and the run-branch
workflow ops (ensure/branch/commit/diff) — all against real local repos, no
network."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from git import Actor, Repo

from spidey.workspaces.infrastructure.git_provider import (
    GitPythonProvider,
    build_authenticated_url,
)


class _Settings:
    allowed_git_hosts: ClassVar[list[str]] = ["github.com"]


def _provider() -> GitPythonProvider:
    return GitPythonProvider(_Settings())  # type: ignore[arg-type]


class TestTokenInjection:
    def test_token_injected_as_x_access_token(self) -> None:
        url = build_authenticated_url("https://github.com/o/r.git", "ghp_tok")
        assert url == "https://x-access-token:ghp_tok@github.com/o/r.git"

    def test_no_token_leaves_url_unchanged(self) -> None:
        url = "https://github.com/o/r.git"
        assert build_authenticated_url(url, None) == url


class TestLocalHead:
    async def test_reads_head_of_local_repo(self, tmp_path: Path) -> None:
        repo = Repo.init(tmp_path / "r")
        (tmp_path / "r" / "f.txt").write_text("x", encoding="utf-8")
        repo.index.add(["f.txt"])
        author = Actor("Test", "test@example.com")
        commit = repo.index.commit("init", author=author, committer=author)
        repo.close()

        result = await _provider().head_commit(str(tmp_path / "r"))
        assert result is not None
        assert result.head_commit == commit.hexsha

    async def test_non_repo_returns_none(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert await _provider().head_commit(str(plain)) is None


class TestCloneUrlValidation:
    async def test_clone_rejects_disallowed_host(self, tmp_path: Path) -> None:
        from spidey.workspaces.infrastructure import UrlPolicyError

        with pytest.raises(UrlPolicyError):
            await _provider().clone(
                url="https://gitlab.example/o/r.git",
                branch=None,
                token=None,
                destination=str(tmp_path / "dest"),
            )


class TestRunBranchWorkflow:
    async def _init_workspace(self, tmp_path: Path) -> str:
        """A plain (non-git) workspace tree, like a local ingestion result."""
        root = tmp_path / "ws"
        root.mkdir()
        (root / "app.py").write_text("print('v1')\n", encoding="utf-8")
        return str(root)

    async def test_ensure_repo_initializes_and_sets_local_identity(self, tmp_path: Path) -> None:
        path = await self._init_workspace(tmp_path)
        await _provider().ensure_repo(path, author_name="Spidey", author_email="agent@spidey.local")
        repo = Repo(path)
        try:
            with repo.config_reader() as config:
                assert config.get_value("user", "name") == "Spidey"
                assert config.get_value("user", "email") == "agent@spidey.local"
        finally:
            repo.close()

    async def test_ensure_repo_is_idempotent_on_existing_repo(self, tmp_path: Path) -> None:
        path = await self._init_workspace(tmp_path)
        provider = _provider()
        await provider.ensure_repo(path, author_name="A", author_email="a@x.local")
        await provider.ensure_repo(path, author_name="B", author_email="b@x.local")
        repo = Repo(path)
        try:
            with repo.config_reader() as config:
                assert config.get_value("user", "name") == "B"
        finally:
            repo.close()

    async def test_branch_commit_diff_lifecycle(self, tmp_path: Path) -> None:
        path = await self._init_workspace(tmp_path)
        provider = _provider()
        await provider.ensure_repo(path, author_name="Spidey", author_email="agent@spidey.local")
        await provider.ensure_branch(path, "spidey/run-1")

        # First commit lands the pre-existing tree on the run branch.
        first = await provider.commit_all(path, message="chore(run): baseline")
        assert first is not None

        # An edit shows up in the working-tree diff, then commits atomically.
        (Path(path) / "app.py").write_text("print('v2')\n", encoding="utf-8")
        (Path(path) / "new.py").write_text("x = 1\n", encoding="utf-8")
        diff = await provider.diff(path)
        assert "-print('v1')" in diff
        assert "+print('v2')" in diff
        assert "new.py" in diff  # brand-new files are part of the diff

        second = await provider.commit_all(path, message="feat(run): step 1")
        assert second is not None
        assert second != first

        repo = Repo(path)
        try:
            assert repo.active_branch.name == "spidey/run-1"
            assert str(repo.head.commit.message).startswith("feat(run): step 1")
            # Branch-vs-base diff covers the whole run.
            run_diff = await provider.diff(path, base=first)
            assert "+print('v2')" in run_diff
        finally:
            repo.close()

    async def test_commit_all_on_clean_tree_returns_none(self, tmp_path: Path) -> None:
        path = await self._init_workspace(tmp_path)
        provider = _provider()
        await provider.ensure_repo(path, author_name="S", author_email="s@x.local")
        await provider.ensure_branch(path, "spidey/run-2")
        assert await provider.commit_all(path, message="one") is not None
        assert await provider.commit_all(path, message="two") is None

    async def test_ensure_branch_is_idempotent_and_reuses_existing(self, tmp_path: Path) -> None:
        path = await self._init_workspace(tmp_path)
        provider = _provider()
        await provider.ensure_repo(path, author_name="S", author_email="s@x.local")
        await provider.ensure_branch(path, "spidey/run-3")
        await provider.commit_all(path, message="baseline")
        await provider.ensure_branch(path, "spidey/run-3")  # second call: checkout only
        repo = Repo(path)
        try:
            assert repo.active_branch.name == "spidey/run-3"
        finally:
            repo.close()

    async def test_diff_before_any_commit_uses_empty_tree(self, tmp_path: Path) -> None:
        path = await self._init_workspace(tmp_path)
        provider = _provider()
        await provider.ensure_repo(path, author_name="S", author_email="s@x.local")
        diff = await provider.diff(path)
        assert "+print('v1')" in diff  # everything is an addition vs the empty tree
