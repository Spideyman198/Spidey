# ADR-0014: Kubernetes readiness — compose-first delivery, K8s-shaped design

**Status:** Accepted · 2026-07-09

## Context
v1 ships on Docker Compose (single-host, portfolio-runnable), but the architecture must be
deployable to Kubernetes without redesign: Helm charts, config/secrets strategy, ingress,
autoscaling. The hard part is not the stateless services — it is the sandbox, whose v1 adapter
drives the host Docker socket (unavailable/unacceptable on K8s).

## Decision
- **K8s-readiness as M0 design constraints:** 12-factor env-only config, stateless API, health +
  readiness endpoints, graceful shutdown (SIGTERM drains SSE and Celery), one image many roles,
  migrations as a separate step — these cost nothing now and make Helm mechanical.
- **Helm chart in M14** (`deploy/helm/spidey/`): api Deployment (HPA), per-queue worker
  Deployments (**KEDA** on queue depth — the true load signal), beat with leader election,
  pre-upgrade Alembic Job, ingress-nginx + cert-manager with SSE-aware settings, NetworkPolicies
  deny-by-default, PSS `restricted`, External Secrets Operator (SOPS fallback). Databases via
  operators or `external*` endpoints — charts do not pretend stateful services on K8s are free.
- **Sandbox on K8s = second `Sandbox` adapter: Kubernetes Jobs** in a dedicated locked-down
  namespace (no SA token, deny-all NetworkPolicy, limits, `activeDeadlineSeconds`), gVisor
  runtimeClass as the isolation upgrade. No Docker socket mounts, no DinD, ever.

## Alternatives considered
- **K8s from day one** — deployment complexity taxes every milestone and the reviewer quickstart
  (`docker compose up` is the portfolio's front door). Rejected.
- **Compose-only, K8s "someday"** — the sandbox fork proves this postpones a real architectural
  decision until it's a rewrite. Rejected: the port + adapter decision is made now, cheap.
- **DinD / socket mount on K8s** — privileged containers or node-compromise equivalence. Rejected
  unconditionally.

## Consequences
- (+) The only K8s-specific application code is one Sandbox adapter; everything else is packaging.
- (+) KEDA-on-queue-depth documents a correct autoscaling story rather than the reflexive CPU HPA.
- (−) Helm chart is deferred value: nothing validates it until M14 → mitigated by kind-based chart
  CI (lint + install + smoke) when it lands, and Conftest policies on manifests from day one.
- (−) Job-per-execution has higher latency than warm Docker containers → acceptable for test/CI
  workloads; pooling noted as a future optimization behind the same port.
