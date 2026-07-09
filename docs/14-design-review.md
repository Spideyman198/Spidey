# 14 — Architecture Validation (Principal Design Review)

Record of the pre-implementation design review (2026-07-09). Scope: the full architecture as
documented in docs 01–13. Verdict: **approved for M0 with the scoping decisions and risk register
below.** This document is the honesty ledger — what we deliberately did *not* build matters as much
as what we did.

## 1. Over-engineering identified and cut (or fenced)

| Candidate | Decision | Rationale |
|---|---|---|
| Event-driven agent control flow (item 5 as literally stated) | **Rejected** — events observe, LangGraph controls ([ADR-0011](adr/0011-events-observation-not-control.md)) | Choreography would re-implement checkpointing/interrupts implicitly and un-debuggably |
| Runtime OPA policy engine | **Fenced to CI** (Conftest on infra files) | Runtime policies need typed context + unit tests with the code; Rego sidecar = second language + service for no v1 need |
| Microsoft-style GraphRAG (community summaries) | **Cut**; graph-neighbor expansion only | Expensive offline pipeline aimed at corpus-thematic questions, not code-change tasks |
| Cross-encoder reranking + context compression at v1 | **Deferred to M13, eval-gated** | Inference dependency + latency before there's a measured precision gap to close |
| Neo4j, Elasticsearch, LiteLLM proxy, Loki, MinIO, RUM | **Cut or optional** | Each is a stateful service whose job an existing component covers at v1 scale; every one has a port or config seam if evidence demands it |
| Full SWE-bench in CI | **Cut**; curated task set + SWE-bench-lite subset post-v1 | Full runs are a compute project; a portfolio needs the *methodology* demonstrated, credibly |
| Per-PR live-LLM evals | **Rejected**; T1 is fixture-based and free | Flaky, slow, expensive PR CI is how eval culture dies (doc 10 §4) |
| Runtime browser tooling on by default | **Off by default, untrusted tier** | SSRF/exfiltration surface disproportionate to v1 value |
| Eight separate memory databases | **Rejected**; typed records in one store | The contracts differ; the infrastructure doesn't have to (doc 07) |

## 2. Hidden technical debt — surfaced and scheduled

| Debt | Where it hides | Plan |
|---|---|---|
| Celery(sync) ↔ asyncio agent runtime seam | worker entrypoint | Contained in one helper; integration-tested for cancellation/timeout semantics (M7); revisit worker model only if it leaks |
| LangGraph API churn | agents/graph | Version-pinned; nodes depend on our ports, not LangChain types; T2 eval gate on upgrades (ADR-0002) |
| Tool-schema translation per provider | llm adapters | Conformance test matrix per adapter (ADR-0012); OpenAI-compatible adapter consolidates Ollama/vLLM/Azure |
| Prompt packs as code | agents/prompts | Versioned, replay-gated (T1); re-bless is a reviewed commit |
| Windows dev vs Linux prod drift | sandbox, paths | Docker-first dev, devcontainer parity, `SafeFileSystem` tested against NTFS junctions AND posix symlinks |
| Redis stream retention vs replay guarantees | events | Outbox in PG is the durable record; Redis is transport — loss there is re-relayable (doc 08 §4) |

## 3. Scalability bottleneck analysis

| Bottleneck | Limit | Mitigation now / later |
|---|---|---|
| Single Redis (broker + streams + rate limits + cache) | ~10³ concurrent runs | Fine for v1 by orders of magnitude; roles are config-separable to distinct instances later |
| Postgres write amplification (events + checkpoints + audit) | Heavy agent concurrency | Outbox batching, JSONB payloads, partitioned `run_events` by month; checkpoint compaction |
| Qdrant memory footprint at many workspaces | RAM-bound | Per-workspace collections → shardable; quantization available; snapshots for archival |
| Embedding throughput on large-repo ingest | Provider rate limits | Batched + queued per provider budget; incremental indexing makes it a one-time cost |
| LLM provider rate limits under parallel runs | Provider tier | Gateway-level token-bucket per provider + run admission control; multi-provider routing (ADR-0012) as relief valve |
| SSE fan-out on one API process | ~10⁴ connections | Stateless SSE relay scales horizontally behind the proxy; cursors make reconnects cheap |

## 4. Security gaps found in review → closed in docs

1. MCP tool-definition drift (rug pull) had no control → **pinning + drift alarm** (doc 05 §4).
2. Memory as an injection persistence channel → **write gate + no mid-run writes** (doc 07 §3).
3. Replay capture could persist secrets → **redaction at capture, not read** (doc 08 §5).
4. Eval LLM-judge as a gaming target → **execution-based grading priority, judge audits** (doc 10 §2).
5. K8s sandbox story was implicit → **Jobs adapter + gVisor path made explicit** (doc 12 §2, ADR-0014).
6. Audit trail depended on telemetry stack → **audit plane decoupled** (doc 09 §5).

## 5. Testing gaps → closed

LLM nondeterminism in CI → fixture replay (T1). Approval-gate bypass → explicit adversarial tests
per boundary (tests/security). Trace completeness → span-tree walking test (doc 09 §2).
Migration downgrades → every Alembic migration ships tested downgrade (doc 12 §4). Coverage
thresholds set where they mean something (domain/application 90 %) rather than a vanity global.

## 6. Operational risks (residual — accepted with eyes open)

| Risk | Acceptance rationale |
|---|---|
| Docker Desktop dependency for dev on Windows | Hard requirement documented (01 §7); devcontainer as fallback |
| Kernel-level sandbox escape (shared kernel) | No-net + non-root + quotas make it hard; gVisor upgrade path defined; documented in risk register not hidden |
| Cost runaway from agent loops | Triple guard: step budgets, token budgets, global circuit-breaker kill switch + cost alerts |
| Solo-maintainer bus factor | Mitigated by exactly the docs discipline this review enforces |
| LLM provider outage | Graceful degradation + multi-provider routing; runs park at checkpoints, resume later |

## 7. Sign-off checklist

- [x] Every technology has an ADR or documented justification with alternatives
- [x] Every "requested but rejected/deferred" item has a written rationale (§1)
- [x] Every trust boundary has named controls and planned attack-shaped tests
- [x] Every quality claim is measurable by the eval framework
- [x] Milestones re-sequenced so nothing depends on a later milestone
- [x] User approval to begin M0 (granted 2026-07-09)

## 8. Final maintainability & readiness review (pre-freeze)

Final pass before freeze, focused on long-term single-maintainer viability. Outcome: **no
architectural changes required**; five simplifications adopted:

| # | Simplification | Rationale |
|---|---|---|
| S1 | Bounded-context packages are created **in the milestone that implements them** — no empty `domain/application/infrastructure` shells in M0 | Empty scaffolding is placeholder code by another name; doc 03 describes the *target* tree |
| S2 | Observability services (OTel collector, Jaeger, Prometheus, Grafana) run under a compose **profile** (`obs`), on by default in `make dev`, skippable via `make dev-min` | Full stack for the demo story; fast core loop for daily development on one machine |
| S3 | `qdrant-client` dependency deferred to M4; M0 health checks probe Qdrant over plain HTTP | A dependency should arrive with the code that uses it |
| S4 | M0 ships Grafana provisioning + one platform dashboard; feature dashboards land with the features they observe (doc 09 §6 schedule unchanged) | Dashboards for non-existent metrics are decoration |
| S5 | Docs CI = markdownlint + internal-link check; the Mermaid compile check is deferred | GitHub renders Mermaid natively; a headless-chromium CI step is disproportionate flake risk for a solo maintainer |

Point-by-point findings against the review items:

1. **Complexity:** every remaining component maps to an FR/NFR or a §1 fence; nothing survives on
   "nice to have". The §1 cut list stands.
2. **Dependencies / lock-in:** all frameworks sit behind first-party ports (`ChatModel`,
   `VectorIndex`, `Sandbox`, `GraphStore`, `ArtifactStore`, `EventPublisher`); LangGraph touches
   only `agents/graph`; LangChain proper is absent from the dependency tree. Dependencies arrive
   milestone-by-milestone (S1/S3), each named in its milestone's design note.
3. **Context ownership:** one owner per capability, dependencies flow one way
   (interfaces → contexts → platform; never platform → context, never context → context internals)
   — enforced by import-linter from M0, not convention.
4. **Contract conventions (binding from M0):** ports are typed `Protocol`s/ABCs whose docstrings
   state pre/post-conditions and error semantics; events carry `schema_version` with
   additive-only evolution (breaking = new type); REST is versioned under `/api/v1` with additive
   evolution inside a version; MCP tool definitions are versioned and pinned (doc 05). Consumers
   compile against contracts, never implementations.
5. **Independent testability:** replay (fixture playback needs only recorded artifacts), evaluation
   (runs against fakes or live via the same ports), observability (no-op OTel exporters in tests),
   security pipeline (each scanner is an independent CI job), MCP (conformance tests against an
   in-memory server) — each verified in isolation; none imports another's internals.
6. **Single-engineer cost curve:** the stateful surface is three services + one volume; the paved
   road is `docker compose up` + Makefile; scanners run in CI, not in the developer's face;
   milestone gates prevent half-built subsystems from accumulating.
7. **Incrementality:** each milestone leaves `main` releasable with green CI by its Definition of
   Done; the dependency order in doc 04 was re-verified — no forward references.
8. **First-impression audit:** README leads with what/why/how-to-run; docs are numbered and
   cross-linked; no fake badges; the polish story is doc 13 and lands as scaffolding in M0.
9. **Git workflow (confirmed, doc 13 §3):** Conventional Commits, feature branches + solo PRs with
   the DoD template, SemVer, GitHub Releases drafted by CI and published by the owner, Keep a
   Changelog. **Nothing is ever pushed by tooling — the owner pushes.**
10. **Principal readiness verdict:** residual risks are §6's, unchanged and accepted. No remaining
    weaknesses warrant redesign.

### ❄️ Architecture frozen for Version 1.0 (2026-07-09)

Changes from this point require a superseding ADR justified by a critical flaw discovered during
implementation — not preference. Implementation begins with M0.
