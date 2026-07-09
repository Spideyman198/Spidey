# 06 — Retrieval Architecture

Retrieval quality is the ceiling on agent quality — an agent that retrieves the wrong context
writes the wrong code. This document defines the full retrieval flow: hybrid search, graph
augmentation, reranking, and compression — and which parts ship in v1 versus which are
**eval-gated** (adopted only when the evaluation harness proves they pay for their complexity).

## 1. Retrieval flow

```mermaid
flowchart LR
    q([Query + intent]) --> qp[Query processing\nsymbol extraction · filters]
    qp --> dense[Dense search\nQdrant vectors]
    qp --> sparse[Sparse search\nBM25 · Qdrant sparse vectors]
    qp --> sym[Exact symbol lookup\nPostgres]
    dense & sparse --> fuse[RRF fusion\n+ metadata filters]
    sym --> fuse
    fuse --> graph[Graph expansion\nKG neighbors, decayed]
    graph --> rerank[Cross-encoder rerank\n*v2, eval-gated*]
    rerank --> comp[Context compression\n*v2, eval-gated*]
    comp --> frame[Provenance data-framing]
    frame --> out([Budgeted context])
```

## 2. Stage detail

**Dense retrieval** — syntax-aware chunks (function/class units with `module > class > method`
header paths) embedded via the provider layer, stored in Qdrant with payload:
`{path, span, lang, symbol_kind, symbol, commit, workspace_id}`.

**Sparse retrieval (BM25)** — colocated in the *same Qdrant collection* as named sparse vectors
with server-side IDF, so hybrid dense+sparse fusion is a single query to a single service
(amendment to [ADR-0004](adr/0004-qdrant.md)). BM25 catches what embeddings miss in code:
exact identifiers, error strings, config keys.
*Alternatives rejected:* Elasticsearch (a fourth stateful service for one feature), Postgres FTS
(not BM25-ranked, weak code tokenization).

**Exact symbol lookup** — the `symbols` table answers "definition of X" deterministically;
merged into fusion with a strong prior. Embeddings should never be asked questions an index can
answer exactly.

**Fusion** — Reciprocal Rank Fusion across the three lists (rank-based, so no score-calibration
problem between cosine and BM25), then metadata filters (language, path prefix, symbol kind).

**Graph expansion (GraphRAG, scoped)** — top-k seeds are expanded one to two hops through the
knowledge graph (callers, callees, imports, overrides) with per-hop score decay; graph
relationships are emitted as structured facts alongside the chunks ("`parse_config` is called by
`Server.__init__` at src/server.py:42"). This is the *useful* 20 % of GraphRAG for code.
*Consciously not adopted:* Microsoft-style community detection + LLM-generated hierarchical
summaries — an expensive offline pipeline whose payoff is corpus-wide thematic questions, not
code-change tasks. Documented as a revisit-if-evals-demand-it item.

**Cross-encoder reranking (v2, M13)** — a local reranker (ONNX-served, e.g. bge-reranker class)
rescoring the fused top-50 → top-10. Deferred because it adds an inference dependency and latency;
it enters only if the M4 retrieval eval suite shows precision@k headroom that fusion can't close.

**Context compression (v2, M13)** — deduplicate overlapping chunks, collapse imports, reduce
low-relevance files to signatures, pack to the token budget by marginal relevance. Same eval gate.

**Provenance data-framing (v1, non-negotiable)** — every retrieved item enters prompts wrapped in
inert data frames with source attribution; retrieved text is never concatenated as instructions.
This is a security control (retrieval injection), not an option.

## 3. Indexing lifecycle

- **Incremental:** content-hash diffing from the workspace sync (M2) drives re-parse → re-embed →
  upsert of only changed files; deletions tombstone vectors and symbols in the same transaction
  scope as graph-edge updates.
- **Snapshot consistency:** each index pass produces an `index_snapshot` record; searches read the
  latest complete snapshot, so a half-finished re-index never serves mixed results.
- **Poisoning scan at index time:** chunks are screened for instruction-pattern payloads
  ("ignore previous instructions", tool-call mimicry, prompt-boundary characters); hits are indexed
  but flagged `suspect`, surfaced in search results as such, and additionally neutralized at
  framing time. Detection details in [11-security.md](11-security.md).

## 4. Evaluation hooks

The retrieval eval suite (golden query → expected files/symbols per benchmark repo) reports
precision@k, recall@k, and MRR from M4 onward, runs in CI, and is the gate for every v2 feature —
see [10-evaluation.md](10-evaluation.md).
