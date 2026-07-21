# M13 — Retrieval Performance Profile & NFR-2 Verification

**Date:** 2026-07-21 · **Scope:** the CPU-bound stages M13 adds to the search path, and how the
**NFR-2** search-latency budget (`search < 500 ms p95 on a 100k-chunk index`) decomposes across the
retrieval pipeline · **NFR-2**

> Reranking and compression add work to every search. This report measures that added work directly,
> shows it is a negligible fraction of the NFR-2 budget, and states which budget terms are verified
> here versus on the live tier — nothing is renegotiated.

## 1. What was profiled

`scripts/profile_retrieval.py` microbenchmarks the pure stages M13 introduces, over a synthetic
60-candidate pool of ~40-line chunks, 3000 timed iterations each. It deliberately does **not** time
model inference or the Qdrant query — those are model/hardware/index-bound and are measured on the
live tier — so these numbers isolate *the code M13 adds*.

Reproduce:

```bash
cd backend && python ../scripts/profile_retrieval.py --pool 60 --iters 3000
```

## 2. Results (pool = 60, iters = 3000)

| Stage | p50 (µs) | p95 (µs) | p99 (µs) | mean (µs) | In request path? |
| --- | ---: | ---: | ---: | ---: | --- |
| `rerank_fusion` (lexical score + `rerank_hits`) | 1722.7 | 1988.9 | 2436.5 | 1750.2 | yes |
| `context_compression` (10 hits) | 435.9 | 523.3 | 730.5 | 446.2 | yes (when enabled) |
| `provenance_framing` (10 hits) | 13.2 | 19.9 | 31.8 | 14.1 | yes |
| `ndcg_at_5` | 3.0 | 3.2 | 4.6 | 3.1 | no (eval only) |

**Combined request-path p95 ≈ 2.5 ms** (rerank + compression + framing). NDCG is an evaluation
metric, not part of a live search.

`rerank_fusion` here is dominated by the **model-free lexical scorer** tokenizing 60 chunks; the
pure fusion (`rerank_hits`: normalize + convex blend + stable sort) is a small fraction of it. The
number is an *upper bound* for the fusion overhead and a *lower bound* stand-in for the reranker
stage — the ONNX cross-encoder replaces the lexical scorer with model inference (see §3).

## 3. NFR-2 budget decomposition (search < 500 ms p95, 100k chunks)

| Term | Where the time goes | Order of magnitude | Verified |
| --- | --- | --- | --- |
| Query embedding (dense + sparse, fastembed) | ONNX embed of one query | single-digit → ~20 ms (CPU) | live tier |
| **Vector hybrid query (Qdrant, dense + sparse RRF)** | HNSW search over 100k chunks — **dominant term** | tens → low-hundreds ms | M14 load test |
| Reranker — lexical (default) | tokenize + score the pool | **< 2 ms** | **here (measured)** |
| Reranker — ONNX cross-encoder (when configured) | cross-encoder over ~30–60 pairs | ~20–80 ms (CPU) | live tier |
| Fusion + compression + framing | pure Python (`rerank_hits`, `compress_hits`, `frame_hits`) | **< 3 ms p95** | **here (measured)** |

**Finding.** The M13-added pure-CPU stages consume **< 3 ms p95** — under ~0.6% of the 500 ms budget.
Even with the ONNX cross-encoder, the added stages (~tens of ms) sit comfortably beside the dominant
Qdrant term within budget. The reranker widens first-stage oversampling from 4× to 6×, a modest
increase in the pool the Qdrant query returns and the reranker scores, already reflected above.

**Verification / renegotiation.** Nothing is renegotiated. The stages M13 owns are measured here and
are negligible. The end-to-end `search < 500 ms p95 on a 100k-chunk index` figure depends chiefly on
the Qdrant term, which is a function of index size and HNSW parameters on real hardware; it is
verified by the **M14 load test on the API + SSE** (docs/04 §M14 exit) against a populated index,
which is the milestone that owns live perf verification. This report establishes that M13 does not
threaten that budget.

## 4. Indexing & agent-step hot paths

- **Indexing** is incremental (M2 SHA-256 manifest → only changed files re-parsed/re-embedded) and
  runs on the worker off the request path; M13 changes nothing about it. Parser work is already
  resource-bounded (wall-clock timeout, size cap, depth limit) so one pathological file cannot stall
  a pass.
- **Agent step** overhead from retrieval is bounded by the same < 3 ms CPU stages plus the single
  search call per `codeintel.search` tool invocation; the reranker and compression run once per
  search, not per candidate beyond the bounded pool.

## 5. Carry-forward

The live search p95 on a populated 100k-chunk index, the ONNX cross-encoder's real inference latency,
and compression's token-saving vs content-recall trade-off are measured on the M14 load-test / live
nightly tiers and recorded there.
