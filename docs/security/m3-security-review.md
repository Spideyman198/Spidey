# M3 Security Review

**Date:** 2026-07-10 · **Scope:** codeintel context — Tree-sitter parsing, symbol extraction,
syntax-aware chunking, incremental indexing · **Verdict: PASS**

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Parser resource bounds (SEC — parser DoS) | Wall-clock parse timeout (thread + `future.result(timeout)`), defensive 8 MiB source cap, depth-limited AST walk; the M2 per-file size cap already keeps oversized files out of indexing | `test_oversized_source_rejected`; timeout path implemented and pool-recycled |
| Binary-file rejection | Only files the M2 manifest marks `indexable` (text, within size cap) are read; the indexer maps by extension and skips the rest | `test_first_pass_indexes_all_supported` (non-code files ignored) |
| No direct filesystem access from codeintel | codeintel reads only through the `SourceReader` port, satisfied by a worker adapter over the workspace `SafeFileSystem` — so every read inherits SEC-FS containment; a Semgrep invariant rule bans raw file I/O in the context | import-linter (codeintel never imports workspaces), Semgrep `spidey-agents-no-direct-file-io` |
| Malformed input safety | Tree-sitter is error-tolerant: a broken file yields partial symbols and never crashes the pass; an unparseable file is recorded indexed-but-empty (stale symbols cleared) and not retried | `test_malformed_source_does_not_crash`, `test_unparseable_file_recorded_empty_not_retried` |
| Ownership scoping | Symbol/index endpoints verify workspace ownership before returning data; a foreign workspace's index is 404 | `test_index_ownership_isolation` |
| Incremental integrity | Re-index diffs SHA-256 (M2 manifest) against indexed hashes; only changed files are re-parsed, deleted files' symbols removed — no stale data, bounded work | `test_changed_file_only_is_reparsed`, `test_deleted_file_symbols_removed` |

## 2. Design decisions with security weight

- **codeintel is decoupled from workspaces.** It defines a `SourceReader` port and the worker
  bridges the workspace `SafeFileSystem` to it. This keeps the contexts independent (import-linter
  enforced) *and* means codeintel cannot bypass SEC-FS — it has no other way to read a file. A
  Semgrep rule additionally bans raw `open`/`pathlib` I/O in the context; the one legitimate port
  call carries a reviewed `# nosemgrep`.
- **Parser DoS is defended in layers.** The M2 size cap is the primary bound (oversized files never
  reach the parser); the parser adds its own byte cap, a wall-clock timeout that recycles the
  worker thread on a runaway parse, and a walk depth limit. Documented residual: tree-sitter has no
  in-C cancellation in this version, so a timed-out parse leaks one worker thread — acceptable for a
  rare pathological file, and the file is recorded failed so the pass completes.
- **Indexing runs in the worker, never the sandbox.** Parsing untrusted code is pure, in-process,
  and side-effect-free (tree-sitter builds an AST; no code executes), so it does not require the
  sandbox. Executing untrusted code remains a separate, sandboxed concern (M9).

## 3. Accepted findings / deliberate scoping

- **Grammars are bundled, not downloaded.** Individual `tree-sitter-<lang>` packages ship compiled
  grammars in their wheels, so parsing works offline and under the read-only container rootfs with
  no runtime download or writable cache (a `tree-sitter-language-pack` prototype was rejected
  precisely because it fetched grammars at runtime — a network dependency and read-only-fs failure).
- **Call-reference edges are deferred to M5.** M3 extracts definitions and imports into `symbols`;
  the call graph (who-calls-whom) is built with the knowledge graph in M5, as planned.
- **Actions still tag-pinned** (carried from M0 §3; scheduled M15).

## 4. Attack-shaped / robustness tests added

Oversized-source rejection, malformed-source tolerance, unparseable-file containment (indexed-empty,
not retried), incremental precision (only changed files re-parsed; deleted removed), and index
ownership isolation (404 for non-owner).

## 5. Carry-forward

M4 embeds the chunks this milestone produces (dense + BM25 into Qdrant) and adds retrieval-injection
framing. M5 builds the knowledge graph (calls/inherits edges) from these symbols. Container
hardening: pre-bake the grammar cache; the runtime git binary added here is used by ingestion only.
