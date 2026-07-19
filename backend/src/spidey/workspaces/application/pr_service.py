"""PrService — the gated pull-request delivery flow (M10, docs/05).

Turns a run's isolated branch into a pull request: push the branch to the origin
with the workspace's stored (envelope-encrypted) token, then open the PR through
the native GitHub adapter. This runs only *after* the graph's human PR-approval
gate, so a PR is never opened without a person deciding. A workspace with no
GitHub remote (local source) has nowhere to deliver, so the service reports that
rather than failing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spidey.platform.audit import AuditAction
from spidey.workspaces.domain.models import RepositorySource

if TYPE_CHECKING:
    import uuid

    from spidey.platform.audit import AuditLogger
    from spidey.platform.security import SecretCipher
    from spidey.workspaces.domain.ports import (
        GitProvider,
        PrProvider,
        PullRequest,
        WorkspaceStorage,
        WorkspaceStore,
    )


class PrService:
    def __init__(
        self,
        *,
        store: WorkspaceStore,
        storage: WorkspaceStorage,
        git: GitProvider,
        pr_provider: PrProvider,
        cipher: SecretCipher,
        audit: AuditLogger,
    ) -> None:
        self._store = store
        self._storage = storage
        self._git = git
        self._pr = pr_provider
        self._cipher = cipher
        self._audit = audit

    async def deliver(
        self,
        *,
        workspace_id: uuid.UUID,
        branch: str,
        title: str,
        body: str,
    ) -> PullRequest | None:
        """Push ``branch`` and open a PR against the workspace's default branch.
        Returns ``None`` when the workspace has no GitHub remote to deliver to."""
        stored = await self._store.get_with_token(workspace_id=workspace_id)
        if stored is None or stored.workspace.source is not RepositorySource.GITHUB:
            return None

        repo_url = stored.workspace.location
        base = stored.workspace.branch or "main"
        token = self._cipher.decrypt(stored.encrypted_token) if stored.encrypted_token else None
        path = self._storage.path_for(workspace_id)

        await self._git.push_branch(path, branch=branch, url=repo_url, token=token)
        pr = await self._pr.open_pull_request(
            repo_url=repo_url, token=token, head=branch, base=base, title=title, body=body
        )
        await self._audit.record(
            AuditAction.PULL_REQUEST_OPENED,
            outcome="success",
            actor_user_id=stored.workspace.owner_id,
            target=f"workspace:{workspace_id}",
            pull_request=pr.number,
            branch=branch,
        )
        return pr
