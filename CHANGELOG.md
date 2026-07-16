# Changelog

All notable changes to this project are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Pre-1.0, each completed
milestone bumps the minor version (`0.MINOR.z` = milestone number).

## [Unreleased]

### Added

- Complete v1.0 architecture: requirements & threat model, C4 diagrams, 14 ADRs, bounded-context
  design, milestone plan M0–M15, and specialist designs for the MCP tool plane, retrieval, memory,
  events & replay, observability, evaluation, security, and deployment (`docs/`).
- M0 foundations: repository scaffolding, community & governance files, CI/security pipeline,
  Docker Compose stack, configuration & structured logging & telemetry kernel, FastAPI walking
  skeleton with health endpoints, Celery heartbeat, Alembic baseline, and the evaluation harness
  skeleton with tiered CI wiring.
- M1 identity, audit & sessions: Argon2id users; HS256 access tokens with rotating,
  reuse-detecting refresh tokens; RBAC (admin/developer/viewer) enforced per route; Redis
  token-bucket rate limiting and per-account lockout (fail-closed); an append-only `audit_log`
  (database-trigger enforced) with an independent-commit sink for denial evidence; session and
  message CRUD with strict owner scoping; first-run admin bootstrap CLI; and the full versioned
  REST surface under `/api/v1` with OpenAPI. Backed by 143 tests (unit, integration, attack-shaped
  security) at ~90% coverage.
- M2 workspaces & repository ingestion: `SafeFileSystem` two-layer containment (pure path policy +
  symlink/NTFS-junction resolution) as the single guarded file-access path; local-path and
  GitHub-PAT ingestion on Celery workers with durable status transitions; envelope-encrypted PAT
  storage (HKDF + AES-256-GCM); SSRF-guarded clone (HTTPS + host allow-list + private-address
  rejection); `.gitignore`-aware, binary- and size-capped file manifests with SHA-256 change
  detection; per-workspace disk quotas; and owner-scoped workspace APIs. Backed by 224 tests
  (adds SEC-FS junction/symlink/traversal, SSRF, and envelope-encryption attack suites) at ~89%
  coverage.
- M3 parsing & code index: Tree-sitter parsing for Python, JavaScript, TypeScript, Go, Java, and
  Rust via a pluggable language registry; symbol extraction (functions, classes, methods,
  interfaces/structs/enums/traits, imports) with dotted qualified names into a `symbols` index;
  a non-overlapping, header-path-aware chunker feeding M4 embedding; incremental re-indexing driven
  by the M2 SHA-256 manifest (only changed files re-parsed, deleted files removed); resource-bounded
  parsing (wall-clock timeout, size cap, depth limit); ingestion now chains code indexing; and
  owner-scoped symbol/index-status APIs. Backed by 261 tests (adds per-language extraction and
  incremental-index suites) at ~90% coverage. Runtime image now includes git for cloning.
- M4 hybrid semantic search: local, deterministic embeddings via fastembed/ONNX (dense
  `BAAI/bge-small-en-v1.5` + sparse `Qdrant/bm25`, no third-party API, baked into the image) behind
  a new `llm` context; per-workspace Qdrant collections with named dense + BM25 vectors fused
  server-side by reciprocal-rank fusion; incremental vector maintenance (stale vectors purged for
  changed/removed files, idempotent UUID5 point ids); an exact-symbol lexical boost over the semantic
  ranking; and an owner-scoped `/workspaces/{id}/search` endpoint returning full provenance. Security
  (SEC-PI): all retrieved content is wrapped in an inert, attributed data frame with forged-fence
  neutralization before any prompt use, backed by an index-time injection screen that flags `suspect`
  chunks through both the symbol store and the vector payload. Adds a golden-set retrieval quality
  gate (precision@k / recall@k / MRR with blessed baselines) run against live Qdrant in CI. Backed by
  new embedder, vector-index, search, framing, injection, and retrieval-eval suites.
- M5 knowledge graph & graph-augmented retrieval: per-language extraction of call, inheritance, and
  import references (all six languages) into a Postgres knowledge graph (`graph_nodes`/`graph_edges`,
  ADR-0003) built by name-based, workspace-scoped resolution inside the index transaction (no
  symbol/edge drift); recursive-CTE traversals — callers, callees, impact set, neighborhood — each
  bounded by a depth cap, a visited-node accumulator that terminates cycles, and a row limit; an
  owner-scoped graph API (`/workspaces/{id}/graph/{callers,callees,impact,neighborhood}`) returning
  directional relationship facts with `path:line` provenance; and feature-flagged graph-augmented
  search that expands top hits into knowledge-graph facts alongside the ranked chunks. The retrieval
  eval, re-run with the graph built, shows expansion holds ranked-hit quality at the M4 baselines
  (the milestone's eval-driven exit criterion). Backed by new graph-builder, graph-store traversal,
  graph-flow, and graph-API suites.
- M6 provider gateway, tool plane & MCP, event backbone: a first-party **LLM gateway** (ADR-0009/0012)
  — provider-neutral chat types behind a `ChatModel` seam, three adapters covering six targets
  (`anthropic`, one `openai_compatible` for OpenAI/Ollama/vLLM/Azure, `gemini`), a config-only routing
  table with fallback chains, and one middleware seam that enforces retries+backoff, per-scope token/
  cost budgets, response caching, usage metering, and redacted interaction capture for replay —
  un-bypassable because callers never hold an adapter. A **tool plane** (ADR-0010, docs/05): the
  `ToolRegistry` single choke point (RBAC, JSON-Schema validation, side-effect gating [read-only until
  M7 approvals], timeout, non-trusted-output sanitization, events), native code-search tool, the
  **Spidey MCP server** (serves the registry with REST-identical authZ), and safe **external-MCP
  consuming** with tool-set pinning + drift alarms (rug-pull defense) and description injection-screening
  (tool-poisoning defense). An **event backbone** (docs/08): versioned envelope + transactional outbox →
  Redis-Streams relay → persister/metrics consumer groups, and a cursor-resumable **SSE** run stream
  (ADR-0006). Tied together by a scripted-chat vertical slice (user → gateway → tool round-trip →
  events → SSE) proven end to end offline; live multi-provider conformance runs key-gated in CI. Adds
  the `agents` orchestrator context and migrations for the event plane and `llm_interactions`.
- M7 agent runtime: durable, resumable **runs** on an explicit **LangGraph** state machine
  (ADR-0002) — `plan → approve → execute* → finalize`, compiled with a Postgres checkpointer so a
  pause survives an API/worker restart. A structured, **human-editable plan** with a mandatory
  **approval gate**: the run drafts a plan and blocks (a durable `interrupt`) until the owner
  resumes, optionally after editing the steps. **Per-run budgets** (steps/tokens/cost) that halt a
  runaway into `needs_human` rather than spending unbounded (NFR-5), with a human-granted fresh
  window to continue. The **side-effect approval invariant** at the `ToolRegistry` choke point: a
  write/destructive tool runs only against a resolved, `approved` `Approval` scoped to that exact
  tool and run — a grant is never transferable, and reads are the only un-gated path. A run-lifecycle
  control surface (`RunService`) and owner-scoped REST endpoints (create/list/get/cancel/resume,
  plan get/edit, approvals list/resolve) over the shared SSE stream. **Deterministic replay** as the
  M7 exit criterion: a `T1`, LLM-free golden-replay suite reconstructs a run's timeline (plan,
  transcript, status, event sequence) from committed fixtures and fails on any non-determinism or
  drift. Adds `runs`/`plans`/`approvals` tables (LangGraph's own checkpoint tables are created and
  owned by the checkpointer, not Alembic) and the `psycopg[binary]` driver for it.
