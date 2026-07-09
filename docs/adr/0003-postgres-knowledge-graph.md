# ADR-0003: Knowledge graph in PostgreSQL, not a graph database

**Status:** Accepted · 2026-07-09

## Context

FR-2.5 requires a repository knowledge graph (files/modules/symbols; imports/defines/calls/inherits)
answering bounded queries: callers-of, callees-of, impact set to depth N, module neighborhood.
Graph size for target repos: 10⁴–10⁶ nodes.

## Decision

Store the graph as `graph_nodes` / `graph_edges` tables in PostgreSQL with composite indexes, and
implement traversals with recursive CTEs behind a `GraphStore` port with hard depth/row limits.

## Alternatives considered

- **Neo4j** — best-in-class traversal ergonomics, but adds a fourth stateful service (ops, backup,
  auth surface, memory footprint) for queries that are all bounded-depth and index-friendly.
  Rejected: cost without a driving query pattern (no unbounded path-finding or graph algorithms in
  requirements).
- **In-memory NetworkX rebuilt from Postgres** — fast queries but violates NFR-4 (state in process
  memory), poor incremental updates, doesn't scale across workers. Rejected as primary store;
  acceptable later as a per-request cache if profiling demands it.

## Consequences

- (+) One database to operate, back up, and secure; graph writes join the indexing pipeline's
  transactions, so symbols and edges can't drift out of sync.
- (+) `GraphStore` port means adopting Neo4j later is an adapter, not a redesign.
- (−) Deep/analytical graph queries would be slow — explicitly out of scope; the port's depth limits
  make the constraint visible in the API rather than a surprise.
