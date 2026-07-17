"""Run-branch git workflow (M8): isolated branches, scanned atomic commits.

Contract: every agent run works on its own branch (``spidey/run-<id>``) so a
run can never mutate the user's branch; each committed step is atomic and uses
a conventional-commit message; and **no diff reaches a commit without passing
the secret scan** — a credential-shaped hunk blocks the commit as a typed
outcome, never a warning. Everything here is workspace-local; pushing is a
later, separately-gated milestone.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from spidey.platform.security import SecretFinding, scan_for_secrets

if TYPE_CHECKING:
    from spidey.workspaces.domain.ports import GitProvider, WorkspaceStorage

_AUTHOR_NAME = "Spidey Agent"
_AUTHOR_EMAIL = "agent@spidey.local"
_SUBJECT_LIMIT = 72  # conventional-commit subject line cap


class RunBranch(BaseModel):
    """The isolated branch a run works on, plus the diff base for the whole run."""

    model_config = ConfigDict(frozen=True)

    branch: str
    base_commit: str | None  # None only for an empty repo with nothing to baseline


class CommitOutcome(BaseModel):
    """Result of one step commit. ``blocked`` non-empty ⇒ nothing was committed."""

    model_config = ConfigDict(frozen=True)

    commit_sha: str | None = None
    blocked: list[SecretFinding] = Field(default_factory=list[SecretFinding])

    @property
    def committed(self) -> bool:
        return self.commit_sha is not None


def branch_for_run(run_id: uuid.UUID) -> str:
    return f"spidey/run-{run_id}"


class GitWorkflowService:
    def __init__(self, *, git: GitProvider, storage: WorkspaceStorage) -> None:
        self._git = git
        self._storage = storage

    async def prepare_run_branch(self, *, workspace_id: uuid.UUID, run_id: uuid.UUID) -> RunBranch:
        """Ensure the workspace is a repo, check out the run's branch, and
        baseline any pre-existing uncommitted tree so the run's own diff is
        clean. Idempotent — resuming a run lands on the same branch."""
        path = self._storage.path_for(workspace_id)
        await self._git.ensure_repo(path, author_name=_AUTHOR_NAME, author_email=_AUTHOR_EMAIL)
        branch = branch_for_run(run_id)
        await self._git.ensure_branch(path, branch)
        # A local-ingested workspace arrives as a plain tree: commit it as the
        # baseline. A cloned repo is already clean, so this is a no-op.
        await self._git.commit_all(path, message="chore(spidey): run baseline")
        head = await self._git.head_commit(path)
        return RunBranch(branch=branch, base_commit=head.head_commit if head else None)

    async def commit_step(
        self, *, workspace_id: uuid.UUID, run_id: uuid.UUID, step_index: int, summary: str
    ) -> CommitOutcome:
        """Atomically commit the working tree for one plan step — unless the
        diff contains a secret, in which case nothing is committed and the
        findings are returned (SEC-SECRETS)."""
        path = self._storage.path_for(workspace_id)
        diff = await self._git.diff(path)
        if not diff.strip():
            return CommitOutcome()  # nothing to commit
        findings = scan_for_secrets(diff)
        if findings:
            return CommitOutcome(blocked=findings)
        subject = f"feat(run): {summary}"[:_SUBJECT_LIMIT]
        message = f"{subject}\n\nRun: {run_id}\nStep: {step_index}"
        sha = await self._git.commit_all(path, message=message)
        return CommitOutcome(commit_sha=sha)

    async def run_diff(self, *, workspace_id: uuid.UUID, base: str | None) -> str:
        """The run's cumulative diff: committed steps plus the working tree,
        against the recorded base commit (or HEAD when no base is known)."""
        path = self._storage.path_for(workspace_id)
        return await self._git.diff(path, base=base)
