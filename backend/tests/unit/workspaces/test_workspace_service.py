"""WorkspaceService: token encryption at create, ownership, lifecycle."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from spidey.platform.errors import NotFoundError
from spidey.platform.security import SecretCipher
from spidey.workspaces.application import WorkspaceService
from spidey.workspaces.domain.models import IngestionRequest, RepositorySource
from spidey.workspaces.infrastructure import LocalWorkspaceStorage
from tests.unit.workspaces.fakes import FakeAuditLogger, FakeWorkspaceStore

if TYPE_CHECKING:
    from pathlib import Path

OWNER = uuid.uuid4()
OTHER = uuid.uuid4()
MASTER = "an-encryption-master-key-32-chars-minimum"


def _service(tmp_path: Path, store: FakeWorkspaceStore) -> WorkspaceService:
    class _S:
        workspaces_root_path = tmp_path / "workspaces"

    return WorkspaceService(
        store=store,
        storage=LocalWorkspaceStorage(_S()),  # type: ignore[arg-type]
        cipher=SecretCipher(MASTER),
        audit=FakeAuditLogger(),
    )


def _github_request(token: str | None) -> IngestionRequest:
    return IngestionRequest(
        name="repo",
        source=RepositorySource.GITHUB,
        location="https://github.com/o/r.git",
        branch="main",
        token=token,
    )


class TestCreate:
    async def test_github_token_is_encrypted_at_rest(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        workspace = await _service(tmp_path, store).create(
            owner_id=OWNER, request=_github_request("ghp_secret"), request_id=None
        )
        stored_token = store.tokens[workspace.id]
        assert stored_token is not None
        assert "ghp_secret" not in stored_token  # ciphertext, not plaintext
        assert SecretCipher(MASTER).decrypt(stored_token) == "ghp_secret"

    async def test_local_source_stores_no_token(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        request = IngestionRequest(
            name="local", source=RepositorySource.LOCAL, location="/srv/repo", branch=None
        )
        workspace = await _service(tmp_path, store).create(
            owner_id=OWNER, request=request, request_id=None
        )
        assert store.tokens[workspace.id] is None


class TestOwnership:
    async def test_other_owner_cannot_get(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        service = _service(tmp_path, store)
        workspace = await service.create(
            owner_id=OWNER, request=_github_request(None), request_id=None
        )
        with pytest.raises(NotFoundError):
            await service.get(owner_id=OTHER, workspace_id=workspace.id)

    async def test_list_scoped_to_owner(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        service = _service(tmp_path, store)
        await service.create(owner_id=OWNER, request=_github_request(None), request_id=None)
        await service.create(owner_id=OTHER, request=_github_request(None), request_id=None)
        assert len(await service.list(owner_id=OWNER)) == 1


class TestDelete:
    async def test_delete_removes_row_and_root(self, tmp_path: Path) -> None:
        store = FakeWorkspaceStore()
        service = _service(tmp_path, store)
        workspace = await service.create(
            owner_id=OWNER, request=_github_request(None), request_id=None
        )
        # Simulate an ingested tree on disk.
        root = tmp_path / "workspaces" / str(workspace.id)
        root.mkdir(parents=True)
        (root / "f.txt").write_text("x", encoding="utf-8")

        await service.delete(owner_id=OWNER, workspace_id=workspace.id, request_id=None)
        assert workspace.id not in store.workspaces
        assert not root.exists()

    async def test_delete_missing_is_not_found(self, tmp_path: Path) -> None:
        service = _service(tmp_path, FakeWorkspaceStore())
        with pytest.raises(NotFoundError):
            await service.delete(owner_id=OWNER, workspace_id=uuid.uuid4(), request_id=None)
