"""Consumer groups over the event firehose (docs/08 §4).

Each group reads ``events:all`` independently, at-least-once, and is idempotent
on the ULID ``event_id``:
- **persister** projects every event into ``run_events`` (the durable spine).
- **metrics** projects LLM/tool facts into Prometheus counters.

Both are driven one batch at a time by a periodic pump (workers), so they need
no long-lived loop and restart cleanly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter
from sqlalchemy.dialects.postgresql import insert as pg_insert

from spidey.platform.events.contracts import (
    EventEnvelope,
    LlmCallCompleted,
    ToolInvocationCompleted,
)
from spidey.platform.events.orm import RunEventRecord
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from spidey.platform.events.streams import StreamBus

_FIREHOSE = "events:all"
_BATCH = 128
_logger = get_logger("spidey.events.consumers")

# Counter names omit the `_total` suffix; prometheus_client appends it.
_LLM_TOKENS = Counter(
    "spidey_llm_tokens",
    "LLM tokens accounted, by provider/model/role and direction.",
    ["provider", "model", "role", "direction"],
)
_LLM_COST = Counter(
    "spidey_llm_cost_usd",
    "LLM spend in USD, by provider/model/role.",
    ["provider", "model", "role"],
)
_TOOL_CALLS = Counter(
    "spidey_tool_invocations",
    "Tool invocations, by tool/side-effect/outcome.",
    ["tool", "side_effect", "outcome"],
)


class EventPersister:
    """Consumer group ``persister`` → ``run_events``."""

    group = "persister"

    def __init__(self, bus: StreamBus, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._bus = bus
        self._session_factory = session_factory

    async def pump(self, *, consumer: str = "worker") -> int:
        await self._bus.ensure_group(_FIREHOSE, self.group)
        messages = await self._bus.read_group(
            _FIREHOSE, group=self.group, consumer=consumer, count=_BATCH, block_ms=0
        )
        if not messages:
            return 0
        async with self._session_factory() as session:
            for _mid, data in messages:
                await self._persist(session, EventEnvelope.model_validate_json(data))
            await session.commit()
        for mid, _data in messages:
            await self._bus.ack(_FIREHOSE, group=self.group, message_id=mid)
        return len(messages)

    @staticmethod
    async def _persist(session: AsyncSession, envelope: EventEnvelope) -> None:
        # ON CONFLICT DO NOTHING: a re-delivered event is an idempotent no-op.
        await session.execute(
            pg_insert(RunEventRecord)
            .values(
                event_id=envelope.event_id,
                event_type=envelope.event_type,
                schema_version=envelope.schema_version,
                occurred_at=envelope.occurred_at,
                run_id=envelope.run_id,
                session_id=envelope.session_id,
                workspace_id=envelope.workspace_id,
                actor=envelope.actor,
                trace_id=envelope.trace_id,
                span_id=envelope.span_id,
                payload=envelope.payload,
            )
            .on_conflict_do_nothing(index_elements=[RunEventRecord.event_id])
        )


class MetricsProjector:
    """Consumer group ``metrics`` → Prometheus counters."""

    group = "metrics"

    def __init__(self, bus: StreamBus) -> None:
        self._bus = bus

    async def pump(self, *, consumer: str = "worker") -> int:
        await self._bus.ensure_group(_FIREHOSE, self.group)
        messages = await self._bus.read_group(
            _FIREHOSE, group=self.group, consumer=consumer, count=_BATCH, block_ms=0
        )
        for mid, data in messages:
            self._project(EventEnvelope.model_validate_json(data))
            await self._bus.ack(_FIREHOSE, group=self.group, message_id=mid)
        return len(messages)

    @staticmethod
    def _project(envelope: EventEnvelope) -> None:
        if envelope.event_type == LlmCallCompleted.event_type:
            p = LlmCallCompleted.model_validate(envelope.payload)
            _LLM_TOKENS.labels(p.provider, p.model, p.role, "prompt").inc(p.prompt_tokens)
            _LLM_TOKENS.labels(p.provider, p.model, p.role, "completion").inc(p.completion_tokens)
            _LLM_COST.labels(p.provider, p.model, p.role).inc(p.cost_usd)
        elif envelope.event_type == ToolInvocationCompleted.event_type:
            t = ToolInvocationCompleted.model_validate(envelope.payload)
            _TOOL_CALLS.labels(t.tool, t.side_effect, t.outcome).inc()
