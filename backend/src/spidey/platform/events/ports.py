"""Event-plane ports. Producers depend on :class:`EventPublisher` only."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from spidey.platform.events.contracts import EventEnvelope


class EventPublisher(Protocol):
    """Stages a domain event for publication in the caller's unit of work.

    The concrete adapter writes to the transactional outbox in the *same* session
    as the state change, so the event and the fact it describes commit atomically
    (docs/08 §4). Producers never touch Redis or the relay directly."""

    def add(self, envelope: EventEnvelope) -> None: ...
