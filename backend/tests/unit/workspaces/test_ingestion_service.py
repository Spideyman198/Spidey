"""IngestionService: clone/copy → inventory → status, with real storage + cipher."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from spidey.platform.security import SecretCipher
from spidey.workspaces.application import IngestionService
from spidey.workspaces.domain.models import RepositorySource, WorkspaceStatus
from spidey.workspaces.infrastructure import LocalWorkspaceStorage
from tests.unit.workspaces.fakes import FakeAuditLogger, FakeGitProvider, FakeWorkspaceStore

if TYPE_CHECKING:
    from pathlib import Path

OWNER = uuid.uuid4()
MASTER = "an-encryption-master-key-32-chars-minimum"


def _storage(tmp_path: Path) -> LocalWorkspaceStorage:
    class _S:
        workspaces_root_path = tmp_path / "workspaces"

    return LocalWorkspaceStorage(_S())  # type: ignore[arg-type]


def _service(
    tmp_path: Path,
    store: FakeWorkspaceStore,
    git: FakeGitProvider,
    *,
    max_workspace_bytes: int = 10_000_000,
) -> IngestionService:
    return IngestionService(
        store=store,
        storage=_storage(tmp_path),
        git=git,
        cipher=SecretCipher(MASTER),
        audit=FakeAuditLogger(),
        max_workspace_bytes=max_workspace_bytes,
        max_file_bytes=1_000_000,
    )


async def _github_workspace(store: FakeWorkspaceStore, *, token: str | None) -> uuid.UUID:
    cipher = SecretCipher(MASTER)
    encrypted = cipher.encrypt(token) if token else None
    workspace = await store.create(
        owner_id=OWNER,
        name="repo",
        source=RepositorySource.GITHUB,
        location="https://github.com/o/r.git",
        branch="main",
        encrypted_token=encrypted,
    )
    return workspace.id


class TestGithubIngestion:
    async def test_clone_ready_with_manifest(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        git = FakeGitProvider()
        wid = await _github_workspace(store, token="ghp_realtoken")

        await _service(tmp_path, store, git).ingest(wid)

        workspace = store.workspaces[wid]
        assert workspace.status is WorkspaceStatus.READY
        assert workspace.head_commit == "a" * 40
        assert workspace.file_count == 2
        assert {e.path for e in store.manifests[wid]} == {"README.md", "app.py"}

    async def test_token_is_decrypted_before_clone(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        git = FakeGitProvider()
        wid = await _github_workspace(store, token="ghp_realtoken")

        await _service(tmp_path, store, git).ingest(wid)

        # The service must hand the git provider the *plaintext* token.
        assert git.received_token == "ghp_realtoken"

    async def test_clone_failure_marks_failed_and_cleans_up(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        git = FakeGitProvider(fail=True)
        wid = await _github_workspace(store, token="ghp_realtoken")

        await _service(tmp_path, store, git).ingest(wid)

        workspace = store.workspaces[wid]
        assert workspace.status is WorkspaceStatus.FAILED
        assert workspace.error  # a safe, generic message
        assert not (tmp_path / "workspaces" / str(wid)).exists()

    async def test_corrupt_token_fails_with_safe_message(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        wid = await _github_workspace(store, token="ghp_realtoken")
        store.tokens[wid] = "v1:corrupt:token:value:here"  # undecryptable

        await _service(tmp_path, store, FakeGitProvider()).ingest(wid)

        assert store.workspaces[wid].status is WorkspaceStatus.FAILED
        assert store.workspaces[wid].error == "stored credential could not be decrypted"


class TestQuota:
    async def test_over_quota_fails_and_cleans_up(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        git = FakeGitProvider(files={"big.txt": b"x" * 5000})
        wid = await _github_workspace(store, token=None)

        await _service(tmp_path, store, git, max_workspace_bytes=100).ingest(wid)

        assert store.workspaces[wid].status is WorkspaceStatus.FAILED
        assert not (tmp_path / "workspaces" / str(wid)).exists()


class TestLocalIngestion:
    async def test_local_copy_ready(self, tmp_path: Path) -> None:
        source = tmp_path / "src"
        source.mkdir()
        (source / "hello.py").write_text("print('hi')\n", encoding="utf-8")
        (source / "data.bin").write_bytes(b"\x00\x01\x02")

        store = FakeWorkspaceStore()
        workspace = await store.create(
            owner_id=OWNER,
            name="local",
            source=RepositorySource.LOCAL,
            location=str(source),
            branch=None,
            encrypted_token=None,
        )
        await _service(tmp_path, store, FakeGitProvider()).ingest(workspace.id)

        result = store.workspaces[workspace.id]
        assert result.status is WorkspaceStatus.READY
        assert {e.path for e in store.manifests[workspace.id]} == {"hello.py", "data.bin"}

    async def test_missing_local_source_fails(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        workspace = await store.create(
            owner_id=OWNER,
            name="local",
            source=RepositorySource.LOCAL,
            location=str(tmp_path / "nonexistent"),
            branch=None,
            encrypted_token=None,
        )
        await _service(tmp_path, store, FakeGitProvider()).ingest(workspace.id)
        assert store.workspaces[workspace.id].status is WorkspaceStatus.FAILED


class TestUnknownWorkspace:
    async def test_missing_workspace_is_noop(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        # Should not raise.
        await _service(tmp_path, store, FakeGitProvider()).ingest(uuid.uuid4())
