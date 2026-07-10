"""GitProvider: token injection and local HEAD reading (no network)."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import pytest
from git import Actor, Repo

from spidey.workspaces.infrastructure.git_provider import (
    GitPythonProvider,
    build_authenticated_url,
)

if TYPE_CHECKING:
    from pathlib import Path


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
