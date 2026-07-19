"""GitHubPrProvider — opens a pull request via the GitHub REST API (M10).

Native, gated PR delivery (docs/05): the API host is fixed to ``api.github.com``
(no SSRF surface from the stored repo URL), the token authenticates the call and
is passed only in the Authorization header — never logged, never in an error —
and redirects are disabled. A failed call surfaces GitHub's status, never the
token or request internals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from spidey.platform.logging import get_logger
from spidey.workspaces.domain.ports import PullRequest
from spidey.workspaces.infrastructure.url_guard import UrlPolicyError

if TYPE_CHECKING:
    import httpx

_logger = get_logger("spidey.workspaces.github_pr")
_API = "https://api.github.com"
_MIN_PATH_SEGMENTS = 2  # owner + repo
_HTTP_CREATED = 201


class PrCreateError(UrlPolicyError):
    """PR creation failed for a reason safe to surface (token already scrubbed)."""

    status = 502
    title = "Pull request creation failed"


def _parse_owner_repo(repo_url: str) -> tuple[str, str]:
    """``https://github.com/owner/repo(.git)`` → ``(owner, repo)``. Only the
    github.com host is accepted, so a stored URL cannot redirect the API call."""
    parts = urlsplit(repo_url)
    if parts.hostname not in {"github.com", "www.github.com"}:
        raise PrCreateError("pull requests are only supported for github.com repositories")
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < _MIN_PATH_SEGMENTS:
        raise PrCreateError("could not derive owner/repo from the repository URL")
    owner, repo = segments[0], segments[1]
    return owner, repo.removesuffix(".git")


class GitHubPrProvider:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http = http_client

    async def open_pull_request(
        self,
        *,
        repo_url: str,
        token: str | None,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> PullRequest:
        owner, repo = _parse_owner_repo(repo_url)
        if not token:
            raise PrCreateError("a repository access token is required to open a pull request")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload = {"title": title, "head": head, "base": base, "body": body}
        try:
            response = await self._http.post(
                f"{_API}/repos/{owner}/{repo}/pulls", json=payload, headers=headers
            )
        except Exception:
            # Never let a transport error carry the token/URL into logs.
            _logger.warning("pr_request_failed", owner=owner, repo=repo)
            raise PrCreateError("pull request request failed") from None
        if response.status_code != _HTTP_CREATED:
            _logger.warning("pr_rejected", owner=owner, repo=repo, status=response.status_code)
            raise PrCreateError(f"GitHub rejected the pull request (HTTP {response.status_code})")
        data = response.json()
        return PullRequest(number=int(data["number"]), url=str(data["html_url"]))
