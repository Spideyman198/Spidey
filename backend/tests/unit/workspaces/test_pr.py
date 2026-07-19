"""PR delivery: GitHubPrProvider parsing/errors + PrService gated flow (no network)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from spidey.workspaces.application import PrService
from spidey.workspaces.domain.models import RepositorySource, Workspace, WorkspaceStatus
from spidey.workspaces.domain.ports import PullRequest
from spidey.workspaces.infrastructure import GitHubPrProvider, PrCreateError


class _Resp:
    def __init__(self, status_code: int, data: dict[str, Any]) -> None:
        self.status_code = status_code
        self._data = data

    def json(self) -> dict[str, Any]:
        return self._data


class _HttpClient:
    def __init__(self, resp: _Resp) -> None:
        self._resp = resp
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _Resp:
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._resp


class TestGitHubPrProvider:
    async def test_non_github_host_is_rejected(self) -> None:
        provider = GitHubPrProvider(_HttpClient(_Resp(201, {})))  # type: ignore[arg-type]
        with pytest.raises(PrCreateError):
            await provider.open_pull_request(
                repo_url="https://gitlab.com/o/r.git",
                token="t",
                head="h",
                base="main",
                title="t",
                body="b",
            )

    async def test_opens_pr_and_never_logs_token(self) -> None:
        client = _HttpClient(
            _Resp(201, {"number": 12, "html_url": "https://github.com/o/r/pull/12"})
        )
        provider = GitHubPrProvider(client)  # type: ignore[arg-type]
        pr = await provider.open_pull_request(
            repo_url="https://github.com/o/r.git",
            token="ghp_secret",
            head="spidey/run-1",
            base="main",
            title="t",
            body="b",
        )
        assert pr == PullRequest(number=12, url="https://github.com/o/r/pull/12")
        # The token goes only in the Authorization header, never the payload.
        assert client.calls[0]["headers"]["Authorization"] == "Bearer ghp_secret"
        assert "ghp_secret" not in str(client.calls[0]["json"])

    async def test_missing_token_is_refused(self) -> None:
        provider = GitHubPrProvider(_HttpClient(_Resp(201, {})))  # type: ignore[arg-type]
        with pytest.raises(PrCreateError):
            await provider.open_pull_request(
                repo_url="https://github.com/o/r",
                token=None,
                head="h",
                base="main",
                title="t",
                body="b",
            )

    async def test_non_201_raises(self) -> None:
        provider = GitHubPrProvider(_HttpClient(_Resp(422, {"message": "no"})))  # type: ignore[arg-type]
        with pytest.raises(PrCreateError):
            await provider.open_pull_request(
                repo_url="https://github.com/o/r",
                token="t",
                head="h",
                base="main",
                title="t",
                body="b",
            )


# ── PrService ─────────────────────────────────────────────────────────────────
class _Stored:
    def __init__(self, workspace: Workspace, encrypted_token: str | None) -> None:
        self.workspace = workspace
        self.encrypted_token = encrypted_token


class _Store:
    def __init__(self, stored: _Stored | None) -> None:
        self._stored = stored

    async def get_with_token(self, *, workspace_id: uuid.UUID) -> _Stored | None:
        return self._stored


class _Storage:
    def path_for(self, workspace_id: uuid.UUID) -> str:
        return "/ws"


class _Git:
    def __init__(self) -> None:
        self.pushed: list[str] = []

    async def push_branch(self, path: str, *, branch: str, url: str, token: str | None) -> None:
        self.pushed.append(branch)


class _PrProvider:
    def __init__(self) -> None:
        self.opened: list[str] = []

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
        self.opened.append(head)
        return PullRequest(number=5, url="https://github.com/o/r/pull/5")


class _Cipher:
    def decrypt(self, token: str) -> str:
        return "plain-" + token


class _Audit:
    def __init__(self) -> None:
        self.records = 0

    async def record(self, *args: object, **kwargs: object) -> None:
        self.records += 1


def _workspace(source: RepositorySource) -> Workspace:
    now = datetime.now(tz=UTC)
    return Workspace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="w",
        source=source,
        location="https://github.com/o/r.git",
        branch="main",
        status=WorkspaceStatus.READY,
        head_commit=None,
        size_bytes=0,
        file_count=0,
        error=None,
        created_at=now,
        updated_at=now,
    )


def _service(store: _Store, git: _Git, pr: _PrProvider, audit: _Audit) -> PrService:
    return PrService(
        store=store,  # type: ignore[arg-type]
        storage=_Storage(),  # type: ignore[arg-type]
        git=git,  # type: ignore[arg-type]
        pr_provider=pr,  # type: ignore[arg-type]
        cipher=_Cipher(),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )


class TestPrService:
    async def test_github_workspace_pushes_opens_pr_and_audits(self) -> None:
        stored = _Stored(_workspace(RepositorySource.GITHUB), encrypted_token="enc")
        git, pr, audit = _Git(), _PrProvider(), _Audit()
        service = _service(_Store(stored), git, pr, audit)
        result = await service.deliver(
            workspace_id=stored.workspace.id, branch="spidey/run-1", title="t", body="b"
        )
        assert result is not None
        assert result.number == 5
        assert git.pushed == ["spidey/run-1"]
        assert pr.opened == ["spidey/run-1"]
        assert audit.records == 1

    async def test_local_workspace_has_nothing_to_deliver(self) -> None:
        stored = _Stored(_workspace(RepositorySource.LOCAL), encrypted_token=None)
        git, pr, audit = _Git(), _PrProvider(), _Audit()
        service = _service(_Store(stored), git, pr, audit)
        result = await service.deliver(
            workspace_id=stored.workspace.id, branch="spidey/run-1", title="t", body="b"
        )
        assert result is None
        assert git.pushed == []
        assert pr.opened == []
