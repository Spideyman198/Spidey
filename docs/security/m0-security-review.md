# M0 Security Review

**Date:** 2026-07-09 · **Scope:** foundations, platform kernel, API skeleton, worker skeleton,
evaluation harness, CI/security pipeline, compose stack · **Verdict: PASS** (one environment-blocked
verification, see §4)

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
|---|---|---|
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

## 4. Environment-blocked verification

Docker is not installed on the development host, so `docker compose up` (image build, container
hardening flags in effect, service-to-service communication) could not be executed live. Mitigation:
compose/Dockerfile validated syntactically and by policy rules; the CI `build` job builds the image
on every push; integration tests (DB/Redis readiness) run in CI against real services. **This gate
must be closed by running `make dev` on a Docker-capable host before M1 work begins.**

## 5. Carry-forward items

M1: Argon2id + JWT + refresh rotation + RBAC + rate limiting + append-only audit (the identity
security review is the next report). M6: MCP boundary controls. M9: sandbox red-team review.
