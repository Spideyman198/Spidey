# ADR-0001: Modular monolith with hexagonal bounded contexts

**Status:** Accepted · 2026-07-09

## Context

The system spans eight distinct concerns (identity, workspaces, code intelligence, agents,
execution, memory, LLM access, delivery) built by a very small team, but must read like software an
enterprise could operate and evolve.

## Decision

One deployable backend organized as bounded contexts, each internally hexagonal
(domain / application / infrastructure). The same image runs as API, Celery worker, or beat via
entrypoint. Layering and context isolation are enforced with import-linter contracts in CI, not
convention alone.

## Alternatives considered

- **Microservices** — network boundaries buy independent scaling/deployment we don't need, and cost
  distributed transactions, service discovery, and much harder local dev and debugging. Rejected.
- **Plain layered monolith (models/services/routes)** — simpler initially, but business logic
  smears across services and swapping adapters (LLM provider, vector store) becomes surgery.
  Rejected.

## Consequences

- (+) Fast local dev, single deployment, easy refactors across contexts, unit-testable core with
  fakes at ports.
- (+) The most extraction-worthy context (`execution`) can become a service later without redesign —
  its boundary is already an interface.
- (−) Discipline required: boundary erosion is the classic monolith failure mode → mitigated by
  CI-enforced import contracts.
- (−) One runtime fault domain; mitigated by worker/API process separation and health-gated deploys.
