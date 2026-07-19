"""Domain-event plane: versioned contracts, transactional outbox, Redis-Streams
relay, consumer-group projectors, and the durable read model (docs/08)."""

from spidey.platform.events.consumers import EventPersister, MetricsProjector
from spidey.platform.events.contracts import (
    EVENT_TYPES,
    ApprovalRequested,
    ApprovalResolved,
    CodeGenerated,
    CommandExecuted,
    CommitBlocked,
    DocsGenerated,
    EventEnvelope,
    EventPayload,
    FixGenerated,
    LlmCallCompleted,
    MessageReceived,
    PlanCreated,
    PullRequestOpened,
    ReviewCompleted,
    RunCompleted,
    RunReported,
    RunStarted,
    RunStatusChanged,
    RunStepCommitted,
    TestsCompleted,
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
    "ApprovalRequested",
    "ApprovalResolved",
    "CodeGenerated",
    "CommandExecuted",
    "CommitBlocked",
    "DocsGenerated",
    "EventEnvelope",
    "EventPayload",
    "EventPersister",
    "EventPublisher",
    "FixGenerated",
    "LlmCallCompleted",
    "MessageReceived",
    "MetricsProjector",
    "OutboxRelay",
    "OutboxWriter",
    "PlanCreated",
    "PullRequestOpened",
    "ReviewCompleted",
    "RunCompleted",
    "RunEventReader",
    "RunReported",
    "RunStarted",
    "RunStatusChanged",
    "RunStepCommitted",
    "StreamBus",
    "TestsCompleted",
    "ToolInvocationCompleted",
    "ToolInvocationStarted",
    "new_event_id",
    "stream_key_for",
]
