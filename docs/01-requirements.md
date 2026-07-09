# 01 — Requirements Analysis

Project codename: **Spidey** — an autonomous coding agent platform (Claude Code / Devin class) built to
enterprise production standards.

## 1. Vision

A self-hosted platform where a user connects a repository (local path or GitHub), and a team of
cooperating LLM agents can understand the codebase, plan changes, write code, run tests in a sandbox,
debug failures, document the result, and open a pull request — with a human approving every
destructive or irreversible action.

The system must be demonstrably **safe to point at untrusted code**: repository content is treated as
hostile input (prompt injection, malicious build scripts), and all execution is containerized and
resource-limited.

## 2. Personas & primary use cases

| Persona | Use cases |
|---|---|
| **Developer** | "Fix this failing test", "Add pagination to this endpoint", "Explain how auth works here", "Upgrade this dependency and fix breakage" |
| **Tech lead / reviewer** | Reviews agent-proposed diffs, approves/rejects terminal commands and PRs, audits agent activity |
| **Platform operator** | Deploys the stack, manages users/roles, monitors cost, latency, and failures, rotates secrets |

## 3. Functional requirements

Requirements are numbered for traceability; milestones (doc 04) reference these IDs.

### FR-1 Workspace & ingestion
- **FR-1.1** Ingest a repository from a local path or a GitHub URL (clone via token) into a managed workspace.
- **FR-1.2** Workspaces are isolated per session/project; all file access is confined to the workspace root (allow-list, path-traversal safe).
- **FR-1.3** Incremental re-ingestion: detect changed files (git diff / content hash) and re-index only those.
- **FR-1.4** Respect ignore rules (`.gitignore`, binary/large-file exclusion, configurable size caps).

### FR-2 Code intelligence
- **FR-2.1** Parse source with Tree-sitter for at minimum: Python, TypeScript/JavaScript, Go, Java, Rust (grammar set is pluggable).
- **FR-2.2** Extract symbols (functions, classes, methods, imports, call references) into a structured index.
- **FR-2.3** Chunk code along syntactic boundaries (not fixed windows) and embed chunks into Qdrant.
- **FR-2.4** Hybrid retrieval: dense vectors + sparse BM25 + exact symbol lookup, fused (RRF) with metadata filters, returning provenance (file, line span, commit). Full flow: [06-retrieval.md](06-retrieval.md).
- **FR-2.5** Repository knowledge graph: nodes = files/modules/symbols, edges = imports/defines/calls/inherits; queryable (e.g. "what calls X", "impact set of changing Y") and used for graph-augmented retrieval (GraphRAG-scoped).
- **FR-2.6** Incremental indexing with snapshot consistency; index-time poisoning screening.
- **FR-2.7** *Eval-gated v2:* cross-encoder reranking and context compression — adopted only if the retrieval eval suite proves the gain (see FR-8).

### FR-3 Agent system
- **FR-3.1** Orchestrated multi-agent runtime (LangGraph): Planner, Coder, Reviewer, Tester, Debugger, Documenter, Terminal agents with a supervising orchestrator.
- **FR-3.2** Planner decomposes a user goal into an editable, persisted task plan.
- **FR-3.3** Coder edits files only through audited, validated tools (no free-form shell for edits).
- **FR-3.4** Reviewer critiques diffs against the goal + repo conventions before tests run; can send work back.
- **FR-3.5** Tester generates/executes tests in the sandbox; Debugger iterates on failures with a bounded retry budget.
- **FR-3.6** Documenter updates docs/changelogs for the change set.
- **FR-3.7** Every agent step is a typed tool call — recorded, replayable, and attributable.

### FR-4 Execution & delivery
- **FR-4.1** All command execution happens inside ephemeral Docker sandboxes: no network by default, CPU/memory/PID/time limits, non-root, workspace-only mount.
- **FR-4.2** Command allow-list with parameter validation; anything outside the list requires explicit human approval.
- **FR-4.3** Git integration: branch-per-run, atomic commits with structured messages, diff inspection.
- **FR-4.4** Pull request generation on GitHub (title, description, test evidence) — only after human approval.

### FR-5 Memory & persistence
- **FR-5.1** Conversation memory: full message history per session, with token-budgeted context assembly (summarization of older turns).
- **FR-5.2** Session persistence: a run can be stopped and resumed from a durable checkpoint (LangGraph checkpointer in PostgreSQL).
- **FR-5.3** Long-term memory with explicit typed components — working, conversation, repository, semantic, procedural, episodic, evaluation — each with defined ownership, retention, indexing, and lifecycle ([07-memory.md](07-memory.md)); stored with provenance, recalled semantically, user-inspectable and deletable.
- **FR-5.4** Gated memory writes: only the end-of-run distillation step (or explicit user request) may write long-term memory, through a validation gate (PII scrub, injection scan, scope check).

### FR-6 Interaction
- **FR-6.1** Streaming responses (tokens, tool events, plan updates) to the client in real time.
- **FR-6.2** Human approval gates: destructive actions (out-of-allow-list commands, force operations, PR creation, file deletion outside plan) pause the graph until approve/reject.
- **FR-6.3** REST API (versioned, OpenAPI) + React/TypeScript web UI: chat, plan view, diff viewer, approval inbox, run timeline.
- **FR-6.4** MCP as the first-class tool plane: platform tools are exposed via an MCP server under identical authz/approval rules, and external MCP servers (GitHub, PostgreSQL, browser, custom) mount as pluggable, trust-tiered providers ([05-tooling-and-mcp.md](05-tooling-and-mcp.md)).
- **FR-6.5** Real-time agent dashboard: active runs, execution graph state, tool usage, progress, safe reasoning summaries (never raw chain-of-thought), token/latency/cost, failures — driven by the same event stream as the historical timeline.

### FR-7 Replay
- **FR-7.1** Every run is replayable: prompts, responses, tool invocations, events, diffs, token usage, latency, costs, and failures are captured (redacted at capture) — [08-events-and-replay.md](08-events-and-replay.md).
- **FR-7.2** Three replay modes: timeline reconstruction (UI), golden re-execution with recorded fixtures (CI regression), comparative re-run under new config (evaluation).

### FR-8 Evaluation
- **FR-8.1** Evaluation framework from M0, in CI: codegen pass@k, retrieval precision/recall/MRR, agent-task success rate, groundedness/hallucination, safety (injection corpus), latency, token and cost tracking — [10-evaluation.md](10-evaluation.md).
- **FR-8.2** Tiered CI: deterministic LLM-free smoke on every PR; budgeted live suites nightly and at release; baselines updated only by reviewed re-bless commits.

### FR-9 Model providers
- **FR-9.1** Provider-portable model layer: OpenAI, Anthropic, Gemini, Ollama, vLLM, Azure OpenAI — switching and per-role routing (planner vs summarizer models) is configuration only, verified by adapter conformance tests ([ADR-0012](adr/0012-model-provider-registry.md)).

## 4. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Availability | Single-node deployment; graceful degradation when Qdrant/Redis are down (search disabled, core chat still works) |
| NFR-2 | Latency | First streamed token < 2 s p95 after LLM dispatch; search < 500 ms p95 on 100k-chunk index |
| NFR-3 | Scalability | Indexing and agent runs execute on horizontally scalable Celery workers; API is stateless |
| NFR-4 | Durability | No agent state lives only in process memory; crash-restart resumes from checkpoint |
| NFR-5 | Cost control | Per-session token budgets and per-user rate limits; token usage metered and reported |
| NFR-6 | Observability | Structured JSON logs, OpenTelemetry traces across API→worker→LLM, Prometheus metrics, Grafana dashboards |
| NFR-7 | Maintainability | Bounded contexts, ports-and-adapters, strict typing (Pyright strict), ≥ 85 % coverage on domain/application layers |
| NFR-8 | Portability | Entire stack runs via `docker compose up`; CI green on every commit |

## 5. Security requirements & threat model

### Assets
Workspace source code, user credentials/tokens (GitHub PAT, LLM API keys), conversation/memory data,
the host machine itself.

### Threat actors
Malicious repository content (the primary one — the agent *reads and executes* untrusted code),
malicious/compromised users, network attackers, compromised dependencies.

### STRIDE summary (top risks → controls)

| Threat | Vector | Controls |
|---|---|---|
| **Prompt injection** | Instructions embedded in repo files, issue text, search results | Content/instruction separation (retrieved text wrapped in inert data frames with provenance), tool-call allow-lists per agent role, approval gates on side effects, output filtering (SEC-PI) |
| **Arbitrary code execution → host compromise** | Agent runs `npm install`/tests on hostile repo | All execution in ephemeral Docker sandbox: no network (default), non-root, read-only rootfs, cgroup CPU/mem/PID limits, wall-clock timeout, workspace-only bind mount (SEC-SBX) |
| **Secret exfiltration** | Injected instructions ask agent to read env/keys | Secrets never enter agent context; sandbox env is scrubbed; secret-scanning on all agent output and diffs; egress blocked (SEC-SEC) |
| **Path traversal / file escape** | `../../etc/passwd`-style tool args | Canonicalized path validation against workspace root allow-list on every FS tool call (SEC-FS) |
| **Command injection** | Shell metacharacters in tool args | No shell interpolation — argv-array execution only; command allow-list with typed arg schemas (SEC-CMD) |
| **SSRF** | Agent-triggered URL fetches to internal endpoints | URL scheme/host validation, deny private ranges, fetches proxied through a vetting layer (SEC-SSRF) |
| **Injection (SQL/XSS/CSRF)** | API inputs, rendered agent output | Parameterized queries only (SQLAlchemy), strict Pydantic validation, CSP + output encoding in UI, SameSite cookies + CSRF tokens for cookie flows (SEC-WEB) |
| **Resource exhaustion / DoS-by-agent** | Infinite agent loops, fork bombs in sandbox | Step budgets per run, token budgets, rate limiting (Redis), sandbox quotas, Celery time limits (SEC-QOS) |
| **Supply chain** | Malicious transitive dependency | Locked + hash-pinned deps, `pip-audit`/`npm audit` in CI, SBOM generation, Dependabot (SEC-SUP) |
| **AuthN/AuthZ failures** | Token theft, privilege escalation | Short-lived JWT + rotating refresh, RBAC (admin/developer/viewer), audit log of every privileged action (SEC-IAM) |
| **Tool poisoning / rug pull** | Malicious or silently-updated MCP tool descriptions | Tool-definition pinning + drift alarms, description sanitization, trust tiers (SEC-MCP) |
| **Memory poisoning** | Injected content persisted into long-term memory across sessions | Distillation-only writes through a validation gate; inert framing at recall; confidence decay (SEC-MEM) |
| **PII leakage** | Personal data flowing into logs, memories, replay storage, or providers | PII scrubbing at the log pipeline, memory write gate, and replay capture (SEC-PII) |

Trust boundaries, AI-specific threats in depth, and the full security tooling pipeline (CodeQL,
Semgrep, Bandit, Trivy, Syft/CycloneDX SBOM, Cosign signing, OPA/Conftest, Dependabot):
[11-security.md](11-security.md).

Full security requirement IDs (SEC-*) are enforced per-milestone via the security review checklist in doc 04.

## 6. Explicit non-goals (v1)

- Multi-tenant SaaS billing/tenancy isolation (single-org deployment model).
- IDE plugins; fine-tuning models (self-hosted *serving* via Ollama/vLLM is supported through the provider layer).
- Windows-native sandboxing — Docker is a hard runtime requirement for execution features.
- Real-time collaborative editing of agent sessions.
- Full SWE-bench runs in CI (curated agent-task suite + SWE-bench-lite subset post-v1 — see [10-evaluation.md](10-evaluation.md)).

## 7. Assumptions & constraints

- LLM access via provider APIs (Anthropic default; registry keeps providers config-swappable, including local Ollama/vLLM for air-gapped operation).
- Development host: Windows 11 with Docker Desktop; v1 deployment target: Linux/Docker Compose; Kubernetes is a designed-for target with Helm delivery in M14 ([12-deployment.md](12-deployment.md)).
- Python 3.12+, Node 20+.

## 8. Success criteria

1. End-to-end demo: point at a real OSS repo → ask for a bug fix → agent plans, edits, tests in sandbox, human approves → PR opens on GitHub, with the full run visible as a trace.
2. Security demo: a booby-trapped repo (injection payloads in README, malicious `postinstall`) fails to escape the sandbox, exfiltrate secrets, or hijack the agent — with the attempts visible in the audit log.
3. Evaluation harness reports task success rate, token cost, and wall-clock per task across a fixed benchmark suite, tracked over time in CI.
