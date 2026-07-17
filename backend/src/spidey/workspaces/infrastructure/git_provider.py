"""GitProvider adapter over GitPython.

Security posture: the URL is SSRF-validated before any network call; the access
token is injected into the clone URL only in-memory and is scrubbed from every
error path, so a failed clone can never leak a credential into logs or an API
response. The clone runs in a worker thread so the async caller is not blocked.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

from spidey.platform.logging import get_logger
from spidey.workspaces.domain.ports import CloneResult
from spidey.workspaces.infrastructure.url_guard import UrlPolicyError, validate_clone_url

if TYPE_CHECKING:
    from spidey.platform.config import Settings

_logger = get_logger("spidey.workspaces.git")


def build_authenticated_url(url: str, token: str | None) -> str:
    """Inject a token into a clone URL using the GitHub app/PAT convention
    (user ``x-access-token``, token as password). No token → URL unchanged."""
    if token is None:
        return url
    parts = urlsplit(url)
    netloc = f"x-access-token:{token}@{parts.hostname}"
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class GitCloneError(UrlPolicyError):
    """Cloning failed for a reason safe to surface (token already scrubbed)."""

    status = 502
    title = "Repository clone failed"


class GitPythonProvider:
    def __init__(self, settings: Settings) -> None:
        self._allowed_hosts = settings.allowed_git_hosts

    async def clone(
        self, *, url: str, branch: str | None, token: str | None, destination: str
    ) -> CloneResult:
        validate_clone_url(url, allowed_hosts=self._allowed_hosts)
        return await asyncio.to_thread(self._clone_sync, url, branch, token, destination)

    def _clone_sync(
        self, url: str, branch: str | None, token: str | None, destination: str
    ) -> CloneResult:
        auth_url = build_authenticated_url(url, token)
        try:
            if branch:
                repo = Repo.clone_from(auth_url, destination, single_branch=True, branch=branch)
            else:
                repo = Repo.clone_from(auth_url, destination, single_branch=True)
        except GitCommandError:
            # The exception carries the full git command, including the tokened
            # URL — so it is never logged or surfaced. Only the host and git's
            # numeric status are safe to record.
            _logger.warning("clone_failed", host=urlsplit(url).hostname)
            raise GitCloneError("repository could not be cloned") from None
        try:
            head = repo.head.commit
            return CloneResult(head_commit=head.hexsha, branch=repo.active_branch.name)
        finally:
            repo.close()

    async def head_commit(self, path: str) -> CloneResult | None:
        return await asyncio.to_thread(self._head_commit_sync, path)

    @staticmethod
    def _head_commit_sync(path: str) -> CloneResult | None:
        try:
            repo = Repo(path)
        except (InvalidGitRepositoryError, NoSuchPathError):
            return None
        try:
            branch = repo.active_branch.name if not repo.head.is_detached else "HEAD"
            return CloneResult(head_commit=repo.head.commit.hexsha, branch=branch)
        finally:
            repo.close()

    # ── local run-branch workflow (M8) — never touches the network ───────────
    async def ensure_repo(self, path: str, *, author_name: str, author_email: str) -> None:
        await asyncio.to_thread(self._ensure_repo_sync, path, author_name, author_email)

    @staticmethod
    def _ensure_repo_sync(path: str, author_name: str, author_email: str) -> None:
        try:
            repo = Repo(path)
        except (InvalidGitRepositoryError, NoSuchPathError):
            repo = Repo.init(path)
        try:
            # Repository-local identity only: agent commits must never assume —
            # or overwrite — the user's global git configuration.
            with repo.config_writer() as config:
                config.set_value("user", "name", author_name)
                config.set_value("user", "email", author_email)
        finally:
            repo.close()

    async def ensure_branch(self, path: str, branch: str) -> None:
        await asyncio.to_thread(self._ensure_branch_sync, path, branch)

    @staticmethod
    def _ensure_branch_sync(path: str, branch: str) -> None:
        repo = Repo(path)
        try:
            if not repo.head.is_valid():
                # Unborn HEAD (fresh init): checkout -b simply renames it.
                repo.git.checkout("-b", branch)
            elif branch in {head.name for head in repo.heads}:
                repo.heads[branch].checkout()
            else:
                repo.create_head(branch).checkout()
        finally:
            repo.close()

    async def commit_all(self, path: str, *, message: str) -> str | None:
        return await asyncio.to_thread(self._commit_all_sync, path, message)

    @staticmethod
    def _commit_all_sync(path: str, message: str) -> str | None:
        repo = Repo(path)
        try:
            repo.git.add(A=True)
            if not repo.git.status(porcelain=True).strip():
                return None  # clean tree — an empty commit is never created
            return repo.index.commit(message).hexsha
        finally:
            repo.close()

    # git's well-known empty-tree object: the diff base for an unborn HEAD.
    _EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

    async def diff(self, path: str, *, base: str | None = None) -> str:
        return await asyncio.to_thread(self._diff_sync, path, base)

    @classmethod
    def _diff_sync(cls, path: str, base: str | None) -> str:
        repo = Repo(path)
        try:
            # Intent-to-add so brand-new files appear in the diff; commit_all's
            # add(A=True) later converts these to real stages.
            repo.git.add(A=True, N=True)
            target = base or ("HEAD" if repo.head.is_valid() else cls._EMPTY_TREE)
            return repo.git.diff(target, no_color=True)
        finally:
            repo.close()
