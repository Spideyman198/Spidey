# ADR-0004: Qdrant as the vector store

**Status:** Accepted · 2026-07-09

## Context

Semantic search (FR-2.3/2.4) and memory recall (FR-5.3) need vector similarity search with rich
payload filtering (language, path prefix, symbol kind, workspace), incremental upserts keyed by
chunk identity, and snapshot/restore — self-hosted in Docker.

## Decision

Qdrant, one collection per concern (`code_chunks`, `memories`), payload-indexed filters, accessed
through a `VectorIndex` port.

**Amendment (design review, 2026-07-09):** lexical/BM25 retrieval is implemented as **named sparse
vectors in the same Qdrant collections** (server-side IDF), so hybrid dense+sparse search with RRF
fusion is one query to one service. This closed the open question of where BM25 lives —
Elasticsearch (fourth stateful service) and Postgres FTS (not BM25-ranked, weak code tokenization)
were rejected. Retrieval flow: [docs/06-retrieval.md](../06-retrieval.md).

## Alternatives considered

- **pgvector** — seductive consolidation into Postgres (see ADR-0003's logic), but at our scale
  (100k+ chunks × multiple workspaces) HNSW tuning, filtered-search performance, and index rebuild
  ergonomics are markedly better in a dedicated engine; and vector load competing with OLTP inside
  one Postgres complicates capacity reasoning. Rejected for primary search; revisit if ops cost of
  Qdrant ever dominates.
- **Chroma** — fastest to start, weakest operational story (snapshots, filtering maturity) for a
  production-posture project. Rejected.
- **Pinecone/Weaviate Cloud** — managed SaaS conflicts with self-hosted/air-gapped posture. Rejected.

## Consequences

- (+) Strong filtered ANN performance, clean Python client, Docker-native, snapshotable.
- (−) A third stateful service — accepted deliberately here (unlike ADR-0003) because vector search
  is a core workload with real performance requirements, not an auxiliary structure.
- (−) Graceful degradation required: search features fail soft when Qdrant is down (NFR-1), enforced
  by health checks and circuit-breaking in the search service.
