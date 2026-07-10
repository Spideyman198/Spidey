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
