"""Domain-event plane: versioned contracts, transactional outbox, Redis-Streams
relay, consumer-group projectors, and the durable read model (docs/08)."""

from spidey.platform.events.consumers import EventPersister, MetricsProjector
from spidey.platform.events.contracts import (
    EVENT_TYPES,
    EventEnvelope,
    EventPayload,
    LlmCallCompleted,
    MessageReceived,
    RunCompleted,
    ToolInvocationCompleted,
    ToolInvocationStarted,
    new_event_id,
)
from spidey.platform.events.outbox import OutboxWriter, stream_key_for
from spidey.platform.events.ports import EventPublisher
from spidey.platform.events.reader import RunEventReader
from spidey.platform.events.relay import OutboxRelay
from spidey.platform.events.streams import StreamBus

__all__ = [
    "EVENT_TYPES",
    "EventEnvelope",
    "EventPayload",
    "EventPersister",
    "EventPublisher",
    "LlmCallCompleted",
    "MessageReceived",
    "MetricsProjector",
    "OutboxRelay",
    "OutboxWriter",
    "RunCompleted",
    "RunEventReader",
    "StreamBus",
    "ToolInvocationCompleted",
    "ToolInvocationStarted",
    "new_event_id",
    "stream_key_for",
]
