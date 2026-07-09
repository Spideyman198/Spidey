# 03 — Repository Structure

Monorepo. Backend uses a `src/` layout, bounded contexts as top-level packages, each with
`domain / application / infrastructure`. Community/governance files and GitHub scaffolding are
first-class (this is a portfolio flagship — see [13-repo-standards.md](13-repo-standards.md)).

```
spidey/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                  # lint → typecheck → test+coverage → build
│   │   ├── security.yml            # CodeQL, Semgrep, gitleaks(history), pip/npm audit, Trivy, SBOM
│   │   ├── evals.yml               # T1 smoke on PR (LLM-free) · T2 nightly (budgeted live)
│   │   ├── docs.yml                # markdownlint, link check, Mermaid compile, OpenAPI freshness
│   │   └── release.yml             # tag → build, Cosign sign, SBOM attach, DRAFT release (manual publish)
│   ├── ISSUE_TEMPLATE/             # bug_report.yml, feature_request.yml, eval_regression.yml, config.yml
│   ├── PULL_REQUEST_TEMPLATE.md    # DoD checklist: tests, docs, security, eval impact
│   ├── dependabot.yml              # pip + npm + docker + actions, weekly, grouped
│   └── CODEOWNERS
├── .devcontainer/                  # one-click reviewer environment (uv, Node, Docker)
├── backend/
│   ├── pyproject.toml              # uv-managed; ruff / pyright(strict) / pytest config
│   ├── uv.lock                     # hash-pinned
│   ├── alembic/                    # migrations — every one with a tested downgrade
│   ├── src/spidey/
│   │   ├── platform/               # shared kernel — no business logic
│   │   │   ├── config.py           #   pydantic-settings, env-only, fail-fast
│   │   │   ├── errors.py           #   error taxonomy → RFC 9457 responses
│   │   │   ├── logging.py          #   structlog JSON, trace-id binding, PII scrub processor
│   │   │   ├── telemetry.py        #   OTel init, Prometheus registry
│   │   │   ├── security/           #   hashing, JWT, envelope encryption, secret/PII scanning
│   │   │   ├── events/             #   versioned event contracts, outbox writer, stream relay
│   │   │   └── artifacts.py        #   ArtifactStore port + content-addressed volume adapter
│   │   ├── identity/               # domain/ application/ infrastructure/
│   │   ├── workspaces/             #   ingest, sync, SafeFileSystem, git ops, PR service
│   │   ├── codeintel/              #   parsing, symbols, chunking, hybrid retrieval, KG
│   │   ├── agents/
│   │   │   ├── domain/             #   Run, Plan, ToolSpec, trust tiers, budgets, approval rules
│   │   │   ├── application/        #   run lifecycle, ToolRegistry, context assembler
│   │   │   ├── graph/              #   LangGraph nodes/edges (planner, coder, reviewer, …)
│   │   │   ├── prompts/            #   versioned prompt packs per role (replay-gated changes)
│   │   │   └── infrastructure/     #   PG checkpointer, MCP server + client providers
│   │   ├── execution/              #   CommandPolicy, Sandbox port; docker adapter (k8s_jobs @ M14)
│   │   ├── memory/                 #   conversation, typed long-term memory, write gate, recall
│   │   ├── llm/                    #   provider registry, routing, adapters:
│   │   │                           #     anthropic / openai_compatible (OpenAI·Ollama·vLLM·Azure) / gemini
│   │   ├── evaluation/             #   suites, graders, runners (live|fixture), metrics, eval store
│   │   ├── api/                    # thin interface layer: app factory, middleware, v1 routers,
│   │   │                           #   SSE relay, MCP endpoint
│   │   ├── workers/                # celery app + tasks (ingest, index, agent_run, distill, cleanup)
│   │   └── composition.py          # DI wiring: ports → adapters per process role
│   └── tests/
│       ├── unit/                   # domain + application with port fakes (fast, no I/O)
│       ├── integration/            # adapters vs real PG/Qdrant/Redis (testcontainers)
│       ├── e2e/                    # API flows incl. agent run with fixture LLM
│       ├── security/               # attack-shaped: traversal, injection, sandbox escape,
│       │                           #   authz matrix, approval bypass, MCP poisoning, memory gate
│       └── conftest.py
├── frontend/
│   ├── package.json · vite.config.ts · tsconfig.json (strict)
│   ├── src/
│   │   ├── api/                    # OpenAPI-generated client + typed SSE event reducer
│   │   ├── features/               # chat/ plan/ diff/ approvals/ dashboard/ replay/ memory/ auth/
│   │   ├── components/             # shared UI
│   │   └── app/                    # routing, providers, error boundaries
│   └── tests/                      # vitest + testing-library; playwright e2e
├── sandbox/
│   └── Dockerfile                  # hardened execution image, digest-pinned
├── evaluation/                     # DATA & CONFIG only (code lives in spidey/evaluation)
│   ├── datasets/                   # task defs (YAML), pinned repo SHAs, attack corpus
│   ├── baselines/                  # blessed metrics per suite (reviewed re-bless commits only)
│   └── reports/                    # generated (gitignored)
├── deploy/
│   ├── compose/                    # docker-compose.yml + dev/prod overrides (v1 path)
│   └── helm/spidey/                # chart (delivered M14; Conftest-checked from creation)
├── infra/
│   ├── otel/ prometheus/ grafana/  # collector config, scrape config, dashboards-as-code
│   ├── policy/                     # OPA/Conftest policies for Dockerfiles & manifests
│   └── Dockerfile.backend          # multi-stage, non-root
├── docs/
│   ├── 01–14 planning & architecture docs · adr/ · api/openapi.json
│   ├── security/                   # threat-model detail + per-milestone review reports
│   ├── runbooks/                   # deploy, backup/restore, rotation, incident, cost kill-switch
│   ├── guides/                     # developer guide, deployment guide, API usage examples
│   └── assets/                     # demo GIFs/screenshots (placeholders until M12)
├── scripts/                        # bootstrap, seed, sbom, record-demo (VHS)
├── .env.example                    # every variable documented; no real values
├── .pre-commit-config.yaml         # ruff, pyright, gitleaks, markdownlint, commit-msg, eslint
├── Makefile                        # make dev / test / lint / security / eval / docs
├── LICENSE (Apache-2.0) · CONTRIBUTING.md · CODE_OF_CONDUCT.md · SECURITY.md · CHANGELOG.md
└── README.md
```

## Rules that keep the structure honest (CI-enforced)

1. **Layering:** `domain` imports nothing from `application`/`infrastructure`; `application`
   imports domain + ports only; only `composition.py` and interface layers import adapters
   (import-linter contracts).
2. **Context isolation:** cross-context access only via the other context's `application` services.
3. **Interface thinness:** routers/tasks parse → call use case → translate. Zero business logic.
4. **No untyped seams:** Pyright strict; `Any` requires a justifying comment.
5. **Event discipline:** state change + outbox write in one transaction (Semgrep rule); events are
   published facts, never commands.
6. **Security invariants have one home:** all FS access through `SafeFileSystem`, all execution
   through `Sandbox`+`CommandPolicy`, all tool calls through `ToolRegistry`, all LLM calls through
   the gateway (Semgrep rules ban direct `open()`/`subprocess`/SDK imports outside their adapters).
7. **Tests mirror structure**; every security control gets an attack-shaped test in `tests/security/`.
