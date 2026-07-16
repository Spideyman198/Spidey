"""ToolRegistry — the single invocation choke point (docs/05, ADR-0010).

Every tool call, from any provider (native or MCP) and any caller (agent node or
MCP client), passes through ``invoke`` here, so the security invariants live in
one auditable place: schema validation, RBAC, side-effect gating, per-call
timeout, output sanitization for non-trusted providers, and start/complete
events. A tool never raises across this boundary — failure is a typed result.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import jsonschema

from spidey.agents.domain.runs import ApprovalStatus
from spidey.agents.domain.tools import SideEffect, ToolOutcome, ToolResult, TrustTier
from spidey.identity.domain.models import Role
from spidey.platform.events import (
    EventEnvelope,
    ToolInvocationCompleted,
    ToolInvocationStarted,
)
from spidey.platform.logging import get_logger
from spidey.platform.security import looks_like_injection, scrub_text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spidey.agents.domain.ports import ToolProvider
    from spidey.agents.domain.runs import Approval
    from spidey.agents.domain.tools import ToolContext, ToolSpec
    from spidey.platform.events import EventPublisher

_logger = get_logger("spidey.agents.tools")
_MAX_OUTPUT_CHARS = 100_000


class ToolRegistry:
    def __init__(
        self,
        *,
        providers: Sequence[ToolProvider],
        events: EventPublisher | None = None,
        allow_mutations: bool = False,
    ) -> None:
        self._by_name: dict[str, tuple[ToolProvider, ToolSpec]] = {}
        for provider in providers:
            for spec in provider.specs():
                self._by_name[spec.name] = (provider, spec)
        self._events = events
        # M6 ships read-only tools; write/destructive stay gated until the
        # approval flow lands (M7). The flag makes that rollout explicit.
        self._allow_mutations = allow_mutations

    def list_tools(self, role: Role) -> list[ToolSpec]:
        """Specs the caller's role is allowed to see (RBAC-filtered)."""
        return [
            spec for _provider, spec in self._by_name.values() if role.satisfies(spec.required_role)
        ]

    def spec_for(self, name: str) -> ToolSpec | None:
        """The spec for a tool by name, or None — used to gate before invoking."""
        entry = self._by_name.get(name)
        return entry[1] if entry is not None else None

    async def invoke(
        self,
        *,
        name: str,
        arguments: dict[str, object],
        context: ToolContext,
        approval: Approval | None = None,
    ) -> ToolResult:
        entry = self._by_name.get(name)
        if entry is None:
            return ToolResult.error(f"unknown tool {name!r}")
        provider, spec = entry

        if not context.role.satisfies(spec.required_role):
            self._emit_completed(spec, context, ToolOutcome.DENIED, 0)
            return ToolResult.denied("insufficient role for this tool")

        try:
            jsonschema.validate(arguments, spec.input_schema)
        except jsonschema.ValidationError as exc:
            return ToolResult.error(f"invalid arguments: {exc.message}")

        if spec.side_effect is not SideEffect.READ and not self._mutation_permitted(
            spec, context, approval
        ):
            self._emit_completed(spec, context, ToolOutcome.DENIED, 0)
            return ToolResult.denied(
                f"{spec.side_effect.value} tools require a resolved human approval"
            )

        self._emit_started(spec, context)
        started = time.perf_counter()
        result = await self._run(provider, name, arguments, context, spec)
        latency_ms = int((time.perf_counter() - started) * 1000)

        if spec.trust_tier is not TrustTier.TRUSTED and result.ok:
            result = _sanitize(result)
        self._emit_completed(spec, context, result.outcome, latency_ms)
        return result

    def _mutation_permitted(
        self, spec: ToolSpec, context: ToolContext, approval: Approval | None
    ) -> bool:
        """A write/destructive tool runs only with an explicit grant: a resolved,
        approved :class:`Approval` for *this* tool and *this* run, or the blanket
        ``allow_mutations`` escape hatch (tests / trusted internal batch jobs)."""
        if self._allow_mutations:
            return True
        if approval is None or approval.status is not ApprovalStatus.APPROVED:
            return False
        # The approval must be for exactly this tool and, when the call is part of
        # a run, that same run — a grant is never transferable.
        if approval.tool != spec.name:
            return False
        return context.run_id is None or approval.run_id == context.run_id

    @staticmethod
    async def _run(
        provider: ToolProvider,
        name: str,
        arguments: dict[str, object],
        context: ToolContext,
        spec: ToolSpec,
    ) -> ToolResult:
        try:
            return await asyncio.wait_for(
                provider.invoke(name, arguments, context), timeout=spec.timeout_seconds
            )
        except TimeoutError:
            return ToolResult.unavailable("tool timed out")
        except Exception:
            _logger.exception("tool_invoke_failed", tool=name)
            return ToolResult.error("tool invocation failed")

    def _emit_started(self, spec: ToolSpec, context: ToolContext) -> None:
        if self._events is None:
            return
        self._events.add(
            EventEnvelope.of(
                ToolInvocationStarted(
                    tool=spec.name,
                    side_effect=spec.side_effect.value,
                    trust_tier=spec.trust_tier.value,
                ),
                run_id=context.run_id,
                session_id=context.session_id,
                workspace_id=context.workspace_id,
                actor=str(context.actor_user_id),
                trace_id=context.trace_id,
                span_id=context.span_id,
            )
        )

    def _emit_completed(
        self, spec: ToolSpec, context: ToolContext, outcome: ToolOutcome, latency_ms: int
    ) -> None:
        if self._events is None:
            return
        self._events.add(
            EventEnvelope.of(
                ToolInvocationCompleted(
                    tool=spec.name,
                    side_effect=spec.side_effect.value,
                    outcome=outcome.value,
                    latency_ms=latency_ms,
                ),
                run_id=context.run_id,
                session_id=context.session_id,
                workspace_id=context.workspace_id,
                actor=str(context.actor_user_id),
                trace_id=context.trace_id,
                span_id=context.span_id,
            )
        )


def _sanitize(result: ToolResult) -> ToolResult:
    """Non-trusted output is hostile input: redact secrets, screen for injection,
    size-cap — before it can enter any prompt (docs/05 §4)."""
    content = scrub_text(result.content)[:_MAX_OUTPUT_CHARS]
    return ToolResult(
        outcome=result.outcome, content=content, suspect=looks_like_injection(content)
    )
