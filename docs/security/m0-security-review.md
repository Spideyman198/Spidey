# M0 Security Review

**Date:** 2026-07-09 · **Scope:** foundations, platform kernel, API skeleton, worker skeleton,
evaluation harness, CI/security pipeline, compose stack · **Verdict: PASS** (one environment-blocked
verification, see §4)

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Zero hardcoded secrets | All config via `Settings` (env-only, fail-fast); `.env` git-ignored; `.env.example` documented | `test_missing_required_variables_fail_fast`; gitleaks in pre-commit + CI |
| Secret/PII redaction at the log choke point (SEC-PII seed) | `scrub_event_dict` processor in the structlog pipeline: sensitive keys, token shapes (Anthropic/OpenAI/GitHub/AWS/Slack/PEM), URL credentials, email masking, depth-bomb cutoff | `tests/unit/platform/test_scrubbing.py` (10 cases), `test_secrets_redacted_through_pipeline` |
| Secure error handling (SEC-WEB) | RFC 9457 problems only; unexpected exceptions → generic detail + trace id; exception class names, messages, and stack traces never reach clients — including component names in readiness | `TestErrorLeakage`, `test_component_errors_expose_class_name_only` |
| Security headers | nosniff, DENY framing, no-referrer, `default-src 'none'` CSP, no-store — present on success **and on 500s** (innermost-middleware conversion) | `TestSecurityHeaders` incl. `test_hardening_headers_survive_a_500` |
| CORS allow-list | Explicit origins only; `*` rejected at config validation | `test_wildcard_rejected`, `TestCors` |
| Log-injection hygiene | Incoming `X-Request-ID` accepted only if `[A-Za-z0-9-]{8,64}`; otherwise replaced | `TestRequestIdHygiene` (injection + oversize cases) |
| Bounded execution (SEC-QOS seed) | Celery: acks-late, soft/hard time limits on every task; health checks time-boxed (2 s); API body handling via framework limits | `test_every_task_is_time_bounded` |
| Container hardening | Non-root UID 10001, read-only rootfs + tmpfs, `no-new-privileges`, `cap_drop: ALL`, loopback-only published ports, mem/cpu limits; databases publish no ports in the base file | Conftest policies (`docker.rego`) gate Dockerfile + compose in CI |
| Pipeline security (SEC-SUP seed) | gitleaks (pre-commit + full-history CI), Bandit, Semgrep (4 invariant rules + community), CodeQL, pip-audit on the lockfile, Trivy fs/IaC, Syft SBOM, Dependabot | Workflows in `.github/workflows/`; Bandit clean locally (0 medium+) |
| Architecture invariants | import-linter: platform imports no context; interface layers independent; evaluation layered | `lint-imports`: 3/3 contracts KEPT |

## 2. Threats considered for this milestone's surface

The M0 surface is small (health endpoints, metrics, worker heartbeat). Reviewed: information
disclosure via errors (closed, tested), log injection (closed, tested), secrets in logs/spec/image
(closed: redaction pipeline; OpenAPI export uses placeholder DSNs; image contains no env), DoS via
unbounded checks/tasks (time-boxed), CSP/clickjacking on the docs UI (docs route exempted from
`default-src 'none'` only), supply chain (lockfile-only installs, hash-pinned `uv.lock`).

## 3. Accepted findings / deliberate scoping

- **GitHub Actions pinned by version tag, not SHA.** Writing SHAs from memory risks breaking CI at
  first push; Dependabot manages actions weekly, and conversion to SHA pins is an explicit M15
  supply-chain task. Tracked deviation from docs/11 §4.
- **No authentication yet** — no authenticated surface exists; identity lands in M1 and the only
  mutable state is metrics counters.
- **`/metrics` unauthenticated** — standard for scrape endpoints inside the network boundary; it is
  not published outside the compose network in the base file (loopback API only). Revisit at M14
  (NetworkPolicies).

## 4. Environment-blocked verification — CLOSED 2026-07-09

Docker Desktop was installed and the gate was executed live. Evidence: full stack (10 services,
`obs` profile included) built and started via compose `--wait`; `GET /api/v1/health/ready` from the
host returned `200 {status: ok}` with all security headers; worker heartbeat executing on schedule
with trace correlation; traces visible in Jaeger (`spidey` service registered); Prometheus scraping
live app metrics; Grafana healthy; **all 80 tests including the integration suite passed against
the running stack (92 % coverage)**.

The live run caught two defects that static validation had missed — recorded here because they are
exactly why this gate exists:

1. **Compose command truncation (fixed).** The api `command:` used a YAML folded scalar with
   more-indented continuation lines, which *preserves* newlines; `sh -c` received a multi-line
   script and uvicorn silently started without `--host 0.0.0.0`. The loopback healthcheck still
   passed, so `--wait` reported healthy while the API was unreachable from outside the container.
   Lesson captured as comments in both compose files. Residual caveat: an in-container loopback
   healthcheck cannot detect bind-address regressions — external readiness verification (this gate,
   and Playwright e2e from M12) is the guard.
2. **Collector self-metrics unreachable (fixed).** OTel Collector ≥ 0.111 binds internal telemetry
   to localhost by default; Prometheus's scrape of `otel-collector:8888` was down. The metrics
   reader now binds 0.0.0.0 — confined to the isolated compose network, never published to the host.

One hardening-adjacent portability fix: all host-side service URLs now use `127.0.0.1` instead of
`localhost` (Windows resolves localhost to ::1, where Docker Desktop's proxy accepts TCP but routes
nowhere, producing hangs that mimic outages).

## 5. Carry-forward items

M1: Argon2id + JWT + refresh rotation + RBAC + rate limiting + append-only audit (the identity
security review is the next report). M6: MCP boundary controls. M9: sandbox red-team review.
