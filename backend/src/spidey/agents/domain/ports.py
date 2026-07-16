"""Tool-plane ports.

A :class:`ToolProvider` contributes ToolSpecs and an ``invoke`` — the two kinds
are native (in-process, our code) and MCP (a client connection to a server), but
the registry treats them identically. Providers return a :class:`ToolResult`
rather than raising, so a dead MCP server is an expected value, not a crash
(docs/05 §6).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from spidey.agents.domain.runs import (
        Approval,
        ApprovalStatus,
        Plan,
        Run,
        RunBudget,
        RunStatus,
    )
    from spidey.agents.domain.tools import ToolContext, ToolResult, ToolSpec


class ToolProvider(Protocol):
    @property
    def namespace(self) -> str:
        """Prefix for this provider's tools (``codeintel``, ``github``, …)."""
        ...

    def specs(self) -> list[ToolSpec]:
        """The tools this provider offers, fully namespaced."""
        ...

    async def invoke(
        self, name: str, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult: ...


class RunStore(Protocol):
    """Persistence for runs, their plan, and approval gates (M7)."""

    async def create_run(self, run: Run, *, budget: RunBudget) -> None: ...

    async def get_run(self, *, owner_id: uuid.UUID, run_id: uuid.UUID) -> Run | None:
        """Owner-scoped fetch — a foreign run is None (not found)."""
        ...

    async def list_runs(self, owner_id: uuid.UUID) -> list[Run]: ...

    async def set_status(
        self, *, run_id: uuid.UUID, status: RunStatus, error: str | None = None
    ) -> None: ...

    async def get_budget(self, run_id: uuid.UUID) -> RunBudget | None: ...

    async def set_budget(self, *, run_id: uuid.UUID, budget: RunBudget) -> None: ...

    async def save_plan(self, *, run_id: uuid.UUID, plan: Plan) -> None: ...

    async def get_plan(self, run_id: uuid.UUID) -> Plan | None: ...

    async def create_approval(self, approval: Approval) -> None: ...

    async def pending_approvals(self, run_id: uuid.UUID) -> list[Approval]: ...

    async def get_approval(self, approval_id: uuid.UUID) -> Approval | None: ...

    async def resolve_approval(
        self,
        *,
        approval_id: uuid.UUID,
        status: ApprovalStatus,
        decided_by: uuid.UUID,
    ) -> None: ...
