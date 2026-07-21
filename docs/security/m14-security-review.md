# M14 Security Review — Kubernetes/Helm & the Jobs Sandbox

**Date:** 2026-07-21 · **Scope:** the Kubernetes Jobs sandbox adapter, the Helm
chart's security posture (PSS, NetworkPolicies, RBAC, secrets), and the exec
namespace isolation · **Verdict: PASS**

> On Kubernetes the sandbox is the whole security story: the v1 adapter's Docker
> socket is a node-compromise primitive and is never used here. The Jobs adapter
> runs untrusted code as a hardened, deny-all, tokenless, non-retrying Job in a
> PSS-restricted namespace — the same wall the Docker adapter builds, expressed in
> Kubernetes primitives, with zero changes to agents or policy (the port held).

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| No Docker socket / DinD on K8s (ADR-0014) | Untrusted code runs as a Kubernetes Job, never via a mounted socket or privileged pod | `K8sJobsSandbox` / `build_job_manifest` — no host mounts |
| Exec workload cannot reach the API server | `automountServiceAccountToken: false` on every exec Job + the exec SA | `test_k8s_sandbox` hardening asserts; rendered manifest |
| Exec workload has no network | `deny-all` NetworkPolicy (Ingress+Egress) on the `spidey-exec` namespace | `helm template` → exec NetworkPolicy policyTypes `[Ingress, Egress]` |
| Restricted pod security | Pod/container securityContext: `runAsNonRoot`, read-only rootfs, drop ALL caps, no privilege escalation, `RuntimeDefault` seccomp; namespace enforces PSS `restricted` | conftest policy (252 checks pass); `test_k8s_sandbox` |
| Hostile code runs at most once | `backoffLimit: 0` on exec Jobs | manifest assert |
| Hard wall-clock kill + cleanup | `activeDeadlineSeconds` (timeout + grace) + `ttlSecondsAfterFinished` + explicit delete in `finally` | manifest assert; `test_run` always-deletes |
| Single writable mount, path-confined | Workspace mounted as a PVC **subPath** relative to the shared root; a path outside the root is rejected (fail-closed) | `test_subpath_rejects_escape`; `test_bad_workspace_path_fails_closed` |
| The sandbox never crashes the run | API/config errors become `ExecutionResult(exit_code=None, "sandbox unavailable")`, never an exception | `test_api_failure_is_never_raised` |
| Least-privilege cross-namespace grant | Worker gets a narrow Role in `spidey-exec` (jobs + pods/log only), bound to its SA — nothing cluster-wide | `exec-sandbox.yaml` Role/RoleBinding; rendered |
| Deny-by-default app networking | NetworkPolicies: default-deny, then scoped allows (DNS, api-ingress, datastores, worker-egress allow-list) | `helm template` → 6 NetworkPolicies |
| No plaintext secrets in the chart | External Secrets Operator (preferred) or a pre-created Secret / SOPS; values never hold secret material | `secret.yaml`; only a dev placeholder under `devDatabases.enabled` |
| Migrations never race the schema | Alembic runs as a `pre-install,pre-upgrade` Helm hook Job before app pods roll | `migrations-job.yaml` hook annotations |
| Manifests are policy-gated | Conftest rego enforces the restricted invariants on every rendered manifest in CI | `infra/policy/conftest/kubernetes.rego`; 252 checks pass locally |

## 2. Design decisions with security weight

- **The port made this a one-file change.** Sandboxing was built behind the
  `Sandbox` port (ADR-0007) precisely so the K8s fork is new *infrastructure*
  (`k8s_sandbox.py` + `k8s_client.py`) and nothing in agents, policy, or the
  graph moved. The manifest builder is pure and unit-tested; the client plumbing
  is a thin, fakeable seam.
- **Defense is the namespace wall, not the UID.** As with Docker, containment is
  the deny-all network, PSS-restricted admission, tokenless SA, dropped caps, and
  read-only rootfs — not which non-root UID the workload holds.
- **Kubernetes moves two controls to the node/namespace.** The per-pod PID cap is
  a kubelet setting (`--pod-max-pids`, documented as an exec-node prerequisite),
  and network isolation is a namespace NetworkPolicy — both called out so an
  operator cannot silently omit them.
- **Conftest from day one.** The chart ships with a policy that *fails the build*
  if a template ever introduces a privileged, root, writable-rootfs, or
  unpinned-image container — the invariant is enforced mechanically, not by review.

## 3. Accepted findings / deliberate scoping

- **Live kind install + smoke is a dispatchable CI job, not yet a blocking gate.**
  `helm lint`, `helm template`, and `conftest` run on every change and are green
  locally (helm 3.16 + conftest 0.56 verified this build); the full kind
  install + `helm test` (API health + a PSS-restricted sandbox pod) is present in
  `helm.yml` under `workflow_dispatch` until it is proven on a runner — the same
  honest scoping used for the M12 e2e job. This is the ADR-0014 mitigation
  ("kind-based chart CI when it lands").
- **The client plumbing (`k8s_client.py`) is not unit-tested.** It is a mechanical
  translation to the dynamic kubernetes client, exercised on the live/kind tier;
  the orchestration and result mapping it feeds are fully tested against the
  `JobClient` Protocol with a fake.
- **`devDatabases` and the dev Secret placeholder are non-production by
  construction.** They exist only for the self-contained kind smoke path, are
  gated off by default, and carry explicit "never in production" warnings.
- **Egress allow-list defaults to `0.0.0.0/0`.** The default value is permissive
  for a first install; `values-prod.example.yaml` and the value comment require
  tightening to provider ranges in production.

## 4. Attack-shaped / robustness checks

An exec workload cannot reach the API server (no SA token), the network (deny-all),
the host (no socket/host mounts), or persist (read-only rootfs); it runs once
(`backoffLimit 0`), is killed at the deadline, and is always deleted. A workspace
path outside the shared root is refused before a Job is created. A broken API
server yields "sandbox unavailable", never a crash. The chart's restricted
invariants are enforced by conftest on every render, so a future template edit
cannot regress them unnoticed.

## 5. Carry-forward

Promote the kind smoke job to a blocking gate once green on a runner; add the
`runtimeClass: gvisor` option on the exec namespace for kernel-level isolation
(ADR-0014 upgrade path); tighten the egress allow-list to provider CIDRs; and wire
the Prometheus alert rules to Alertmanager routes (paging for audit-write failure
and sandbox policy violations).
