# ADR-0011: Domain events for observation and integration — not for agent control flow

**Status:** Accepted · 2026-07-09

## Context
The design review proposed event-driven internal architecture (Planner → TaskCreated,
Coder → CodeGenerated, …). Taken literally — agents reacting to each other's events — this would
replace LangGraph edges with choreography. We already committed to LangGraph precisely for durable,
interruptible, replayable control flow (ADR-0002).

## Decision
Split by intent:
- **Control flow** (what happens next in a run): LangGraph edges. Synchronous, checkpointed,
  interruptible, explicitly diagrammable.
- **Facts** (what happened): domain events (`TaskCreated`, `CodeGenerated`, `ReviewCompleted`,
  `TestsPassed`, `FixGenerated`, …) published via a transactional outbox → Redis Streams, consumed
  by the SSE relay, timeline persister, audit projector, metrics projector, and memory distiller.
  Consumers can never affect the producing run.
- **Cross-context commands**: synchronous application-service calls — never events.

Contracts: versioned Pydantic envelopes with OTel correlation; at-least-once delivery; idempotent
consumers. Full design: [docs/08-events-and-replay.md](../08-events-and-replay.md).

## Alternatives considered
- **Full choreography (agents react to events)** — implicit execution order, no single place to see
  or checkpoint the flow, interrupts and budgets become distributed problems. Rejected: it
  re-implements the hard parts of LangGraph, badly.
- **No event layer (poll Postgres for UI/audit)** — simpler but couples every observer to write-side
  schemas and gives up replay-by-construction. Rejected.
- **Kafka/RabbitMQ instead of Redis Streams** — stronger streaming semantics we don't need at v1
  scale; Redis is already present. Rejected; the outbox pattern means the transport is swappable.

## Consequences
- (+) Replay, audit, timeline, dashboard, and eval capture all fall out of one event spine.
- (+) The agent graph stays debuggable as a graph.
- (−) Dual-write discipline (state + outbox in one transaction) must be enforced — Semgrep rule +
  code review checklist item.
- (−) Events duplicate some span data; accepted deliberately (doc 09 §3: different consumers,
  different retention).
