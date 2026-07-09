# ADR-0005: Celery + Redis for background execution

**Status:** Accepted · 2026-07-09

## Context

Ingestion, parsing, embedding, and agent runs are long-running (seconds to hours) and must not
occupy API processes. Needs: retries with backoff, time limits, scheduled jobs, horizontal worker
scaling, and observability hooks.

## Decision

Celery with Redis as broker and result backend; task routing by queue (`indexing`, `agent_runs`,
`maintenance`); hard/soft time limits on every task; beat for schedules. OTel context propagated
via task headers.

## Alternatives considered

- **arq / Dramatiq** — lighter and asyncio-native (arq), but thinner ecosystems for routing,
  rate limits, beat scheduling, and monitoring; Celery's operational maturity and legibility to
  reviewers wins for a production-posture project. Rejected.
- **FastAPI BackgroundTasks / asyncio tasks** — in-process, dies with the request lifecycle,
  violates NFR-4. Rejected outright.
- **Kubernetes Jobs** — infrastructure-heavy for v1's compose deployment. Rejected.

## Consequences

- (+) Battle-tested retries/limits/scheduling; workers scale horizontally per queue.
- (−) Celery is sync-first: agent-run tasks manage their own asyncio event loop internally —
  contained in one worker entrypoint helper.
- (−) Redis becomes availability-critical (broker + streams + rate limits) → single well-monitored
  dependency, persistent AOF in compose, and it was already required for rate limiting.
