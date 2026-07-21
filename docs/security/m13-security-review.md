# M13 Security Review — Retrieval v2 (Reranker & Context Compression)

**Date:** 2026-07-21 · **Scope:** the cross-encoder reranker, its ONNX model supply chain, and
extractive context compression — how each touches untrusted retrieved content, the model artifact,
and the bounded-context / no-file-IO invariants · **Verdict: PASS**

> Retrieval v2 adds a new model artifact (an ONNX cross-encoder) and two new transforms over
> retrieved code. Retrieved code is untrusted input, so the review's core question is: can reranking
> or compression let a hostile chunk escape the data frame, and is the new model artifact
> trustworthy? Neither transform alters or un-frames content, and the model is hash-pinned.

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Model artifact is hash-pinned (supply chain) | `CrossEncoderReranker` verifies the on-disk `.onnx` SHA-256 against `rerank_model_sha256` before first use; mismatch, missing artifact, or pin-without-cache all raise `ValidationFailedError` (fail closed) | `tests/unit/llm/test_reranker.py` — match / mismatch / missing / no-cache cases |
| No direct file IO in `codeintel` (SEC invariant) | Reranking and compression are **pure domain** (`reranking.py`, `compression.py`); the only file-touching code — model loading + hash — lives in `llm/infrastructure/reranker.py` | Semgrep `spidey-agents-no-direct-file-io` (scopes `agents`, `codeintel`); llm mirrors the embedders |
| Retrieved content stays inert data (SEC-PI) | Compression only *slices* existing chunk lines (extractive, never rewrites/executes); reranking only *reorders*. All hits still pass through `frame_hits` before any prompt | `frame_hits` unchanged; `suspect` flag asserted to flow through search |
| Provenance stays exact after compression | A compressed hit's `start_line`/`end_line` are recomputed to the kept window, so the data frame's `path:lines` never misattributes trimmed content | `test_compression` re-anchor assertions |
| Reranker cannot be a text-injection vector | The reranker consumes chunk text and returns **floats only**; a hostile chunk can at most change its own rank, never emit instructions or escape the frame | `Reranker` port returns `list[float]`; content path unchanged |
| Bounded work (DoS resistance) | Reranking runs over a bounded pool (`limit × 6`, `limit ≤ 50`); compression is capped by `char_budget` + `per_hit_max_chars`; fusion/NDCG are linear | `test_search` oversample/limit clamps; `test_compression` budget stops |
| Exact-symbol precision preserved | Reranking reorders the pool, then symbol promotion runs, so an exact identifier still surfaces first even if the reranker scores it low | `test_symbol_promotion_survives_reranking` |
| Safe, non-surprising defaults | Reranking defaults to the **model-free lexical** reranker (no download, read-only-rootfs safe); lossy compression is **off by default** | `config.py` defaults; `composition.py` wiring |

## 2. Design decisions with security weight

- **The model adapter lives in `llm`, not `codeintel`.** Loading ONNX weights is file IO, which the
  Semgrep invariant forbids inside `codeintel`/`agents`. Defining the `Reranker` port in
  `codeintel.domain` and satisfying it from `llm.infrastructure` (exactly as the embedders are)
  keeps codeintel free of model loading and preserves bounded-context independence (import-linter).
- **Hash-pin fails closed.** When `rerank_model_sha256` is set, a mismatched or missing artifact
  raises rather than loading — a swapped or corrupted model cannot silently enter the retrieval
  path. When unset, the adapter logs a warning (explicit, not silent) and, in the default posture,
  no external model is used at all (the lexical reranker needs none).
- **Compression is extractive by choice.** An abstractive (LLM) compressor would add a model call and
  a hallucination/injection surface *inside* the retrieval path. Slicing existing lines keeps the
  content byte-for-byte faithful and provenance exact, and adds no new trust boundary.
- **Reordering is not rewriting.** Reranking changes order and the numeric `score`; it never touches
  `content`, `suspect`, or `path`. The SEC-PI frame remains the guarantee; v2 sits entirely upstream
  of it.

## 3. Accepted findings / deliberate scoping

- **Lexical reranker quality is modest by design.** The default reranker is a term-coverage signal,
  not a semantic model — chosen for zero dependencies and read-only-rootfs safety. The ONNX
  cross-encoder is the quality path and is graded on the live tier; adopting the *mechanism* (with a
  no-regression guarantee) is this milestone's claim, not a specific cross-encoder NDCG number.
- **Compression's content-recall cost is measured on the live tier.** Extractive trimming can drop a
  relevant span; this is why it ships disabled and budget-gated. The recall trade-off on a real
  golden set is a live-tier measurement (docs/perf/m13-retrieval-v2-eval §5).
- **Reranker runs inline on the event loop.** Like the embedders' synchronous `embed_query`, the
  reranker's `score` is a synchronous CPU call in the async path; the pool is bounded so the stall is
  small (< 3 ms for the lexical reranker, per the perf report). Offloading model inference to a
  thread pool is a carry-forward if the ONNX cross-encoder's inline cost warrants it.

## 4. Attack-shaped / robustness checks

A hostile chunk cannot escape the data frame through v2: compression slices its own lines (asserted
to re-anchor provenance and honor budgets) and reranking only reorders and rescores (content,
`suspect`, and framing are untouched). A swapped model artifact fails closed under the hash pin
(mismatch/missing/no-cache all raise). Work is bounded (pool ≤ `50 × 6`, compression budgets), so a
large or adversarial result set cannot induce unbounded work. The fusion, compression, and metrics
are pure and unit-tested, so replay stays deterministic.

## 5. Carry-forward

Bake a cross-encoder into the worker image with its SHA-256 committed to `rerank_model_sha256`;
un-gate the live `retrieval` + `retrieval_rerank_ablation` suites at the nightly tier; measure
compression's content-recall trade-off to set a default budget; and, if inline ONNX inference proves
costly, move `score` to a thread pool.
