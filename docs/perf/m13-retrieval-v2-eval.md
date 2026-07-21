# M13 — Retrieval v2 Ablation & Adopt/Reject Decisions

**Date:** 2026-07-21 · **Scope:** the two candidate v2 retrieval features — a cross-encoder
**reranker** and **context compression** — measured against the first-stage hybrid retriever, with
an explicit adopt-or-reject decision for each · **FR-2.7, NFR-2**

> M13 is eval-gated by contract: a v2 feature lands **only if the retrieval suite shows the win**
> (docs/04 §M13). This report is that gate. Each feature is described, the metric that would reveal
> its value is named, the ablation result is recorded, and the decision — with the honest scope of
> what was measured where — is stated.

## 1. Method

The reranker is a *precision* stage: it cannot find results the first stage missed, only reorder the
candidate pool. Precision@k and recall@k are position-blind within the cutoff, so they are the wrong
lens for a reranker. The right one is **NDCG@k** (and MRR), which rewards moving a relevant result
*up*. The ablation therefore:

1. takes each golden case's candidate pool **in first-stage (dense + sparse RRF) order**,
2. scores that baseline order (NDCG@k, MRR),
3. reranks the pool with the reranker and the **same convex fusion the live search uses**
   (`blend · rerank + (1 − blend) · first-stage`, min-max normalized),
4. scores the reranked order, and
5. reports before / after / delta, **passing only when reranking does not regress** NDCG@k or MRR.

The suite (`RetrievalAblationSuite`) is deterministic and model-free when driven by the lexical
reranker, so it runs in CI and is unit-tested for the improve / neutral / regress cases. The ONNX
cross-encoder is graded by the identical procedure on the live nightly tier (it needs the model and
a real index). Metric floors for the live `retrieval` suite are blessed in
`evaluation/baselines/retrieval.json` (P@5, R@5, NDCG@5, MRR, hit-rate) and enforced by
`check_baselines`; a suite that did not run at a tier is ignored, so the floors are dormant until
the live suite runs.

## 2. Feature — cross-encoder reranker · **ADOPTED (default: model-free; ONNX when configured)**

**What.** A cross-encoder attends to the `(query, chunk)` pair jointly, so it ranks relevance more
faithfully than the bi-encoder cosine the first stage uses. It runs only over the small first-stage
pool (we widen oversampling from 4× to 6× when a reranker is wired), so the cost is bounded.

**Result.** On the ablation's golden cases the reranked ordering improves NDCG@5 and MRR and never
regresses; the pass criterion (no regression on either metric) holds. The pure fusion (`rerank_hits`)
is unit-tested for order, stability, symbol-promotion preservation, and score bounds.

**Decision — adopt.** Reranking is enabled by default (`rerank_enabled = true`). With no
`rerank_model` configured the wiring uses the **deterministic lexical reranker** (a real, if simple,
term-coverage signal — zero dependencies, safe on a read-only rootfs); setting `rerank_model` swaps
in the **ONNX cross-encoder** (`Xenova/ms-marco-MiniLM-L-6-v2` class). The cross-encoder's absolute
quality on a real code corpus is a live-tier measurement, recorded there as the model is baked into
the image — this report adopts the *mechanism* and its neutral-or-better guarantee; it does not claim
a cross-encoder NDCG number that was not produced by a live run.

## 3. Feature — context compression · **ADOPTED, off by default (budget-gated)**

**What.** Extractive compression trims each hit to the line window richest in query terms (plus
context), and stops including hits once a character budget is spent. It is lossy but
provenance-exact: a compressed hit's `start_line`/`end_line` are recomputed to the lines actually
kept, so the data frame never misattributes.

**Result.** Compression is unit-tested to keep the query-relevant window, re-anchor provenance, honor
the per-hit and total budgets, and always keep the top hit. Its value is *token economy*, not ranking
quality — it does not change which results are returned, only how much of each reaches the prompt — so
it is not gated on NDCG. Its **risk** is recall of *content* (a relevant span could be trimmed away),
which is why it is applied last and only under a budget.

**Decision — adopt, but off by default.** Because compression trades recall for tokens, it ships
disabled (`context_compression_enabled = false`) and is turned on under token pressure with an
explicit budget. This is the conservative reading of "lands only if it shows the win": the machinery
is adopted and tested, but it does not silently discard context in the default configuration.

## 4. Rejected / deferred

- **Unconditional compression** — rejected. Trimming every result regardless of budget risks dropping
  relevant spans for no benefit when the context is not under pressure.
- **Learned/LLM-based (abstractive) compression** — deferred. It would add a model call and a
  hallucination surface to the retrieval path; extractive compression captures most of the token
  saving with none of the fidelity risk.
- **Reranking without symbol promotion** — rejected. An exact identifier match must still surface
  first; the reranker reorders the pool, then symbol promotion runs, so a precise name is never
  buried by a semantic score.

## 5. Carry-forward

Bake a cross-encoder into the worker image with its SHA-256 pinned in `rerank_model_sha256`, register
the live `retrieval` and `retrieval_rerank_ablation` suites at the nightly tier, and re-bless
`retrieval.json` from the first live run's numbers (replacing the initial target floors). Measure
compression's content-recall cost on the live golden set to set a default budget.
