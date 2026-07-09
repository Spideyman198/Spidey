# ADR-0006: SSE over Redis Streams for client streaming

**Status:** Accepted · 2026-07-09

## Context

FR-6.1: stream tokens, tool events, plan updates, and approval requests to the browser in real time.
Complication: the producer is a Celery worker, not the API process; browsers refresh; the API
restarts; events must also feed the persisted run timeline.

## Decision

Workers publish typed events to a **Redis Stream per run** (`run:{id}:events`); the API exposes
`GET /api/v1/runs/{id}/events` as **SSE**, reading the stream from a client-supplied cursor
(`Last-Event-ID`). Client→server actions (send message, approve, cancel) are ordinary REST posts.

## Alternatives considered

- **WebSockets** — bidirectional capability we don't need (all client actions are request/response),
  at the cost of a second auth path, no native reconnect/cursor semantics, and trickier proxying.
  Rejected; revisit only if a truly interactive channel emerges.
- **Redis pub/sub instead of Streams** — fire-and-forget: a refreshing browser or restarting API
  loses events. Streams give replay, IDs for cursoring, and capped retention. Rejected.
- **Polling** — simple but fails the latency/UX bar for token streaming. Rejected.

## Consequences

- (+) Refresh-safe and restart-safe streaming; the same stream doubles as the source for the
  persisted timeline and audit trail (consumed once into Postgres).
- (+) SSE rides plain HTTP: JWT auth, tracing, and rate limiting middleware all apply unchanged.
- (−) SSE is unidirectional — fine by design above.
- (−) Streams need retention management → capped length (`MAXLEN ~`) + cleanup task after run
  persistence completes.
