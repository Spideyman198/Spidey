# 04 — Milestone Plan

Re-sequenced in the 2026-07-09 design review: evaluation and observability are **continuous
strands** seeded in M0 (not late milestones), retrieval v2 is eval-gated, and Kubernetes delivery
got its own milestone. Sixteen milestones, M0–M15.

> **Definition of Done (every milestone):** design note updated · production-quality code ·
> unit + integration tests green · attack-shaped security tests for the milestone's boundaries ·
> docs updated · security review report in `docs/security/` · eval impact assessed (suites extended
> or explicitly N/A) · CHANGELOG entry · lint/typecheck clean · CI green · demoable.

Implementation of a milestone starts only after explicit approval. **Nothing is ever pushed to
GitHub by tooling or the assistant — pushes/publishes are performed by the repository owner only.**

| # | Milestone | Delivers |
|---|---|---|
| M0 | Foundations, repo standards & CI/security pipeline | NFR-6..8, doc 13 scaffolding, eval skeleton (FR-8 seed) |
| M1 | Identity, API core, audit & sessions | SEC-IAM, SEC-WEB, FR-6.3(API) |
| M2 | Workspaces & repository ingestion | FR-1.*, SEC-FS |
| M3 | Parsing & code index | FR-2.1, FR-2.2 |
| M4 | Hybrid retrieval v1 + retrieval evals | FR-2.3/2.4/2.6, FR-8.1(retrieval) |
| M5 | Knowledge graph & graph-augmented retrieval | FR-2.5 |
| M6 | Provider registry, tool plane & MCP, events/streaming backbone | FR-9.1, FR-6.1, FR-6.4, ADR-0010/0011/0012 |
| M7 | Agent runtime: planner, approvals, replay capture | FR-3.1/3.2, FR-5.1/5.2, FR-6.2, FR-7.* |
| M8 | Coder, Reviewer & git integration | FR-3.3/3.4, FR-4.3 |
| M9 | Sandboxed execution: Terminal & Tester | FR-4.1/4.2, FR-3.5(test), SEC-SBX/CMD/SEC |
| M10 | Debugger, Documenter & PR delivery + agent evals | FR-3.5(debug)/3.6, FR-4.4, FR-8.1(agent) |
| M11 | Long-term memory system | FR-5.3/5.4, SEC-MEM |
| M12 | Web UI & live agent dashboard | FR-6.3(UI), FR-6.5 |
| M13 | Retrieval v2 & performance (eval-gated) | FR-2.7, NFR-2 |
| M14 | Kubernetes/Helm & ops readiness | ADR-0014, doc 12 |
| M15 | Security hardening, supply chain & v1.0 | SEC-SUP, success criteria 1–3 |

---

## M0 — Foundations, repo standards & CI/security pipeline

Full scaffolding per doc 03 including `.github/` (workflows, templates, CODEOWNERS, dependabot),
community files (LICENSE Apache-2.0, CONTRIBUTING, CoC, SECURITY, CHANGELOG), devcontainer,
pre-commit; uv + ruff + pyright(strict) + pytest; compose stack (PG/Redis/Qdrant + OTel collector,
Jaeger, Prometheus, Grafana) with healthchecks and non-root users; pydantic-settings; structlog
(+PII scrub processor stub); OTel bootstrap; FastAPI factory with `/api/v1/health`; RFC 9457 error
middleware; Alembic; Celery heartbeat with trace propagation; **evaluation module skeleton + T1
CI job (empty suites pass)**; security workflow live (CodeQL, Semgrep, gitleaks, Trivy, pip-audit,
SBOM); import-linter + Semgrep invariant rules (doc 03 §rules); Makefile; polished README v1.
**Exit:** `make dev` boots everything; all workflows green; badges real.
**Security focus:** pipeline itself (doc 11 §3) operational; secure error handling; pinned actions.

## M1 — Identity, API core, audit & sessions

Argon2id users; JWT (15 min) + rotating refresh with reuse detection; RBAC (admin/developer/viewer)
as route + tool-level dependency; Redis token-bucket rate limiting; security headers + CORS;
sessions/messages CRUD with ownership authz; **append-only `audit_log` + trigger guard** (the audit
plane, doc 09 §5, starts here); OpenAPI polish + spec export in CI.
**Exit:** authz matrix suite (route × role) green; brute-force lockout + token-reuse tests green.

## M2 — Workspaces & repository ingestion

Workspace lifecycle with disk quotas; local-path + GitHub-PAT ingestion (PAT envelope-encrypted);
`SafeFileSystem` as the only FS path (canonicalization, allow-list, symlink/junction escape
prevention); content-hash change detection; ignore rules + size caps; Celery ingestion with
progress events; clone-URL SSRF guard.
**Exit:** real OSS repo ingested both ways; traversal/symlink/junction/UNC attack tests green.

## M3 — Parsing & code index

Tree-sitter (Python, TS/JS, Go, Java, Rust; pluggable registry); symbol extraction to `symbols`;
syntax-aware chunker with header paths; incremental re-index from M2 hashes; `index_snapshots`
with snapshot-consistent reads; parser timeouts for pathological files.
**Exit:** symbol queries correct on per-language fixtures; incremental path proven (touch one file
→ one file re-indexed).

## M4 — Hybrid retrieval v1 + retrieval evals

Embedding pipeline via gateway (batched/retried/metered); Qdrant collections with **dense + sparse
BM25 named vectors**; RRF fusion + exact-symbol merge + metadata filters; provenance data-framing;
index-time poisoning screen (`suspect` flags); search API. **Retrieval eval suite** (golden
queries → P/R@k, MRR) wired into T1/T2 with baselines.
**Exit:** eval baselines committed; p95 < 500 ms on benchmark repo; framing tests keep planted
injection chunks inert.

## M5 — Knowledge graph & graph-augmented retrieval

`graph_nodes`/`graph_edges` from M3 symbols; recursive-CTE services (callers/callees/impact-set/
neighborhood, bounded depth + row limits); graph facts merged into retrieval (1–2 hop expansion
with decay, doc 06); graph API.
**Exit:** graph correctness fixtures green; retrieval eval shows graph expansion ≥ neutral (else
feature-flagged off — eval-driven honesty starts here).

## M6 — Provider registry, tool plane & MCP, events/streaming backbone

`llm` context: registry + 3 adapters (anthropic, openai-compatible, gemini) with capability
manifests, per-role routing config, fallback chains, conformance suite; retries/budgets/metering/
caching/redacted capture middleware; **tool plane** (doc 05): ToolRegistry choke point, side-effect
classes, trust tiers, native providers wrapped as tools; **Spidey MCP server** (read-only tools);
external MCP client with pinning + drift alarms + sanitization (one `verified` server end-to-end);
**event backbone** (doc 08): contracts, transactional outbox, Redis Streams relay, persister/audit/
metrics consumer groups, SSE endpoint with cursor resume.
**Exit:** scripted chat streams worker→SSE with tool round-trips on two different providers via
config switch; MCP drift alarm demo; T1 replays first recorded fixtures.
**Security focus:** keys never in logs/spans/events; MCP boundary tests (B7); SSE authz.

## M7 — Agent runtime: planner, approvals, replay capture

LangGraph skeleton + PG checkpointer; run lifecycle (create/resume/cancel); Planner with structured
editable plans; conversation memory + token-budgeted context assembly; approval interrupts +
approve/reject API; step/token budgets → `needs_human`; **full replay capture** (`run_events`,
`llm_interactions`, artifact store, capture-time redaction) + timeline reconstruction API.
**Exit:** goal → plan → human edit/approve → resume across API restart; a completed run replays
deterministically from fixtures in T1.
**Security focus:** no side-effect path without approval record (adversarial tests); checkpoint/
replay payloads secret-free (scanned in tests).

## M8 — Coder, Reviewer & git integration

Diff-based edit tools through `SafeFileSystem`; Coder with convention context; Reviewer critique
loop (bounded); branch-per-run, atomic conventional commits, diff API; secret-scan every diff
before context/commit.
**Exit:** scoped change lands on isolated branch in benchmark repo; planted bad edit demonstrably
caught and repaired by review loop.

## M9 — Sandboxed execution: Terminal & Tester

Hardened sandbox image; Docker adapter (net `none`, non-root, RO rootfs, cgroup caps, wall-clock +
output caps); `CommandPolicy` argv-only allow-list; approval gate for off-list/network; egress
proxy for approved installs; Terminal + Tester agents (framework detect → run → structured
results); env scrub + output secret-scan.
**Exit:** booby-trapped repo suite (malicious postinstall, fork bomb, exfil, host probes) fully
contained, attempts audited. **This is the security-critical milestone** — red-team checklist
executed, report published.

## M10 — Debugger, Documenter & PR delivery + agent evals

Debugger (structured failure analysis, bounded patch-retry, escalation); Documenter; GitHub PR
creation behind approval (template: plan summary + test evidence); run reports. **Agent-task eval
suite** (curated tasks on pinned repos) + groundedness suite live in T2.
**Exit:** success criterion 1 end-to-end (fix → tests → approval → PR); first agent success-rate
baseline committed.

## M11 — Long-term memory system

Typed memories (repository/semantic/procedural/episodic — evaluation kind already live) per doc 07;
end-of-run distillation through the write gate (PII scrub, injection scan, scope, dedupe); recall
in context assembly as attributed data; feedback reinforcement/decay; memory management API;
**memory poisoning eval** added to safety suite.
**Exit:** cross-session benefit demonstrated on benchmark repo; deletion removes record + vector
(test); poisoning corpus stays inert.

## M12 — Web UI & live agent dashboard

React SPA (doc 02 §8 stack): auth, streaming chat, plan board, Monaco diff viewer, approval inbox,
**live dashboard** (active runs, graph state, tool usage, safe summaries, tokens/latency/cost,
failures) and **replay timeline** — both from the same event reducer; memory manager; settings.
OpenAPI-generated client; Playwright e2e on fixture LLM.
**Exit:** all M7–M11 flows drivable from UI; e2e green in CI; demo GIFs recorded (doc 13 §6).
**Security focus:** CSP nonce, no unsafe-inline, agent output as text/code only, CSRF, dep audit.

## M13 — Retrieval v2 & performance (eval-gated)

Cross-encoder reranker (ONNX, hash-pinned model) and context compression — each lands **only if
the retrieval suite shows the win**; profiling pass on indexing/search/agent-step hot paths with
findings recorded; NFR-2 targets verified or renegotiated in writing.
**Exit:** eval report justifying every adopted (or rejected) v2 feature; perf report committed.

## M14 — Kubernetes/Helm & ops readiness

Helm chart per doc 12 §3 (api/worker/beat, KEDA, ingress+cert-manager, NetworkPolicies, PSS,
External Secrets/SOPS, migration hook); **K8s Jobs sandbox adapter**; kind-based chart CI (lint/
install/smoke); runbooks complete (deploy, backup/restore, rotation, incident, cost kill-switch);
Grafana dashboards + alert rules finalized (doc 09 §6); load test on API + SSE.
**Exit:** chart installs on kind with smoke suite green incl. one sandboxed execution via Jobs
adapter; runbook walkthrough recorded.

## M15 — Security hardening, supply chain & v1.0

Full re-verification of every SEC-* with tests; Semgrep/CodeQL tuned as gates; SBOM + license
check + Cosign signing in release flow; dependency audit clean; final threat-model review with
residual-risk register; success criterion 2 (booby-trapped repo demo) recorded; CHANGELOG
finalized; `v1.0.0` tagged — release drafted by CI, **published by the owner**.
**Exit:** release checklist signed; all three success criteria demonstrably met.

---

### Deferred / stretch (post-v1)

SWE-bench-lite integration · gVisor/Firecracker sandbox upgrade · LiteLLM behind `ChatModel` for
long-tail providers · Langfuse exporter · Neo4j adapter if graph queries outgrow CTEs ·
GraphRAG community summaries · org multi-tenancy · GitHub Pages docs site.
