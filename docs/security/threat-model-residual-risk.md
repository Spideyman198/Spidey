# Threat Model Review & Residual-Risk Register (v1.0)

Final threat-model review for the v1.0 release. The full trust-boundary analysis
and AI-specific STRIDE additions live in [docs/11](../11-security.md); this
document records the **residual risks** — what remains after the SEC-* controls
([verification matrix](sec-verification-matrix.md)) — with an explicit accept /
mitigate / defer decision for each. Residual risks are owned by the maintainer
(Kenan Eliyan) and reviewed at each release.

## Method

Each primary asset (the host/node, user secrets, the repository under work, the
audit trail, and the model budget) was walked against the STRIDE categories plus
the AI-specific threats (prompt injection, tool poisoning, memory poisoning). A
control either fully addresses a threat (→ SEC-* matrix, green) or leaves a bounded
residual risk recorded below.

## Residual-risk register

| # | Residual risk | Likelihood | Impact | Decision & rationale |
| --- | --- | --- | --- | --- |
| R1 | **Container escape via a kernel 0-day.** The Docker/K8s sandbox is a shared-kernel boundary; a kernel vulnerability could defeat it. | Low | High | **Accept + roadmap.** Non-root, read-only rootfs, dropped caps, seccomp, and no-network shrink the surface; the deny-all NetworkPolicy limits blast radius. gVisor `runtimeClass` on the exec namespace (ADR-0014 upgrade path) is the mitigation, deferred post-v1. |
| R2 | **Prompt injection that stays within granted capability.** Framing prevents instruction confusion, but an agent can still be *steered* toward a permitted-but-undesirable action. | Medium | Medium | **Mitigated, residual accepted.** Every destructive action (write, command, commit, PR) passes a durable human-approval gate, and work lands only on a per-run branch — so the worst case is a bad diff a human declines. |
| R3 | **Egress allow-list too broad by default.** The chart ships `0.0.0.0/0` for worker egress to ease first install. | Medium | Medium | **Mitigate at deploy.** `values-prod.example.yaml` and the value comment require tightening to provider CIDRs; the deploy runbook calls it out. Documented, not code-enforced. |
| R4 | **Per-pod PID cap depends on node config on K8s.** The Job manifest cannot set it; the kubelet `--pod-max-pids` must be configured on exec nodes. | Low | Medium | **Accept + document.** A fork bomb is still bounded by `activeDeadlineSeconds` and memory limits; the deploy runbook lists the kubelet setting as an exec-node prerequisite. |
| R5 | **Live-model evaluation & the kind smoke test are not yet blocking gates.** Retrieval/agent eval on real models and the full kind install run on dispatch/nightly, not per-PR. | Low | Low | **Accept.** The deterministic tiers (unit, attack-shaped, replay, fixture evals) gate every PR; the live tiers gate at their cadence. Un-gating is a CI-wiring task, not a control gap. |
| R6 | **Secret material correctness is operator-owned.** The chart never holds secrets; a misconfigured External Secrets store or a weak key is outside the app's control. | Low | High | **Accept + document.** The key-rotation runbook and Settings' min-length validation (32+ char keys) reduce misuse; the platform fails closed if required secrets are absent. |
| R7 | **Supply-chain trust in unpinned model artifacts.** Embedding/reranker models are external ONNX artifacts. | Low | Medium | **Mitigated.** The reranker is hash-pinned (fails closed on mismatch); embedding models are baked into the image. Extending explicit hash pins to all bundled models is a hardening follow-up. |
| R8 | **A malicious MCP server mounted by an operator.** Trust tiers and definition pinning catch silent drift, but an operator can still mount a hostile server at a high trust tier. | Low | Medium | **Accept + document.** Pinning + drift alarms + sanitization + RBAC bound the risk; mounting external tools is an explicit operator decision, audited. |

## Sign-off

- All **SEC-\*** requirements are controlled and test-verified ([matrix](sec-verification-matrix.md)).
- All residual risks above are **recorded with an explicit decision**; none is an
  unmitigated high-likelihood/high-impact item.
- Roadmap mitigations (gVisor, tighter egress defaults, broader model pinning,
  live-tier gating) are captured as post-v1 follow-ups.

**Reviewed for v1.0** — no blocking residual risk. Re-review at each subsequent
release or on any change to the sandbox, auth, or supply-chain controls.
