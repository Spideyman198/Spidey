# M4 Security Review

**Date:** 2026-07-15 · **Scope:** hybrid semantic search — local embeddings (fastembed), per-workspace
Qdrant vector index, retrieval-injection defense (screen + data-framing) · **Verdict: PASS**

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Retrieval-injection framing (SEC-PI, primary defense) | Every retrieved chunk is wrapped by `codeintel.domain.framing.frame_hits` in an inert, attributed data block before any prompt use; the fence marker cannot be forged (8-`=` runs in content are broken by a zero-width space) and NULs are stripped | `test_framing.py`: attribution, suspect labelling, `test_forged_fence_marker_is_neutralized`, `test_planted_injection_text_survives_as_inert_data` |
| Index-time injection screen (SEC-PI, early warning) | `platform.security.looks_like_injection` flags override/role-spoof/exfiltration signatures; the flag rides with the chunk into both the symbol store (`code_chunks.is_suspect`) and the vector payload, and surfaces on every `SearchHit` | `test_injection.py` (recall + benign non-flagging); `test_indexer.py::test_injection_payload_chunk_is_flagged_suspect`; integration `test_planted_injection_chunk_is_flagged_suspect` |
| Per-workspace tenant isolation | Each workspace has its own Qdrant collection (`<prefix>_<workspace_id.hex>`); a query can only ever touch one collection, so retrieval cannot cross a tenant boundary structurally | `QdrantVectorIndex._collection`; integration `test_search_requires_ownership` (404 for non-owner) |
| Search ownership scoping | The `/search` endpoint verifies workspace ownership before embedding or querying | `test_search_requires_ownership` |
| Incremental vector integrity | On re-index, stale vectors for changed *and* removed files are deleted (keyed on the payload `path` index) before re-embedding — no ghost results, and a deterministic point id (UUID5) makes upsert idempotent | `test_changed_file_clears_stale_vectors_before_reupsert`, `test_removed_file_deletes_its_vectors` |
| No cross-context coupling | codeintel consumes embeddings through its own `DenseEmbedder`/`SparseEmbedder` ports (dependency inversion) and shared `platform.vectors` value types — it never imports `llm` | import-linter (bounded-context independence KEPT) |

## 2. Design decisions with security weight

- **The data frame is the guarantee; the screen is only triage.** Injection detection is heuristic and
  recall-favoring by design (a false positive merely flags `suspect`; a miss is caught downstream). The
  non-negotiable control is that *all* retrieved content is framed inert with provenance before it can
  enter a prompt — the frame does not depend on the screen having fired. Suspect chunks are still indexed
  and retrievable (analysis is the product), just labelled.
- **Fence-forgery is neutralized, not trusted.** A chunk that embeds `======== END RETRIEVED CODE ========`
  or a `system:` turn cannot break out: the framing pass breaks every 8-`=` run with a zero-width space and
  strips NULs, so the only real frame boundaries are the wrapper's own.
- **Tenant isolation is structural, not a filter.** Rather than a `workspace_id` payload filter on a shared
  collection (one missing `must` clause from a cross-tenant leak), each workspace is a separate collection.
  There is no query shape that returns another tenant's vectors.
- **Local, deterministic embeddings.** fastembed/ONNX (ADR-0009) means no third-party API sees repository
  content, no per-call cost, and reproducible vectors. Models are baked into the image, so production does
  no runtime download and runs read-only-rootfs safe.

## 3. Accepted findings / deliberate scoping

- **Qdrant client/server version skew.** The pinned `qdrant-client` is newer than the deployed server
  (1.13.4); the compatibility handshake is disabled (`check_compatibility=False`) because the REST surface
  used (named vectors, RRF fusion, payload-filtered delete) is stable across the skew. Pinning both is
  tracked for a future dependency-alignment pass.
- **Screen coverage is signature-based.** `looks_like_injection` catches known instruction-injection shapes,
  not novel obfuscation; this is acceptable precisely because it is not the primary control. The screen is
  reused for long-term memory poisoning at write time in M11, which also adds an attack corpus.
- **Chunk content is duplicated into the Qdrant payload.** Content lives in the vector payload so a search
  needs no filesystem read on the query path (fewer SEC-FS touchpoints at query time). The duplication is
  bounded (one function/class per chunk) and cleared on re-index.
- **Actions still tag-pinned** (carried from M0 §3; scheduled M15).

## 4. Attack-shaped / robustness tests added

Forged-fence neutralization and planted-injection inertness (unit + integration), injection-screen recall
vs. benign-code non-flagging, suspect-flag propagation into both stores and search results, incremental
vector cleanup on change/removal, per-workspace search ownership isolation (404 for non-owner), and a
golden-set retrieval quality gate (`test_retrieval_eval.py`) enforcing blessed precision@k / recall@k / MRR.

## 5. Carry-forward

M5 builds the knowledge graph from these symbols. M6 adds the LLM gateway (the `llm.application` slice
reserved this milestone) with budgets and metering. M11 reuses `looks_like_injection` for memory-poisoning
defense and adds the injection/poisoning attack corpus to the T-tier evals.
