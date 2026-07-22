# M15 Security Review — Hardening, Supply Chain & v1.0

**Date:** 2026-07-22 · **Scope:** the final security hardening pass — SEC-*
re-verification, the dependency-license gate, CodeQL coverage, the threat-model
residual-risk review, and the v1.0 release flow · **Verdict: PASS**

> M15 adds little new attack surface; it closes gaps and makes the existing
> controls provable. The review's question is not "is a new feature safe?" but
> "is every security requirement controlled, tested, and gated for a 1.0 that runs
> untrusted code?" It is.

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Every SEC-\* is test-verified | Requirement → control → test mapping across all 13 SEC-\* | [sec-verification-matrix.md](sec-verification-matrix.md); all suites green in CI |
| Dependency licenses are gated (SEC-SUP) | Allow-list policy (permissive + weak copyleft; deny GPL/AGPL/SSPL) with verified overrides for two metadata gaps | `scripts/check_licenses.py` (186 deps pass) + `license-checker` (frontend) in `security.yml` |
| CodeQL covers the whole codebase | `security-extended` on **python and javascript-typescript** (frontend gap from M12 closed) | `codeql.yml` matrix |
| Supply chain is signed + inventoried | CycloneDX SBOM + Cosign keyless signing of the release image archive and its SBOM | `release.yml` (build → SBOM → sign → draft) |
| Threat model has a residual-risk register | Eight residual risks recorded with explicit accept/mitigate/defer decisions | [threat-model-residual-risk.md](threat-model-residual-risk.md) |
| Success criteria demonstrably met | All three criteria mapped to attack-shaped / eval / e2e evidence | [success-criteria.md](success-criteria.md) |
| Release is owner-gated | CI drafts on tag; tagging and publishing are owner-only | `release.yml` (`draft: true`, no registry push); [release-checklist.md](release-checklist.md) |

## 2. Design decisions with security weight

- **License gate rejects unknowns, not just known-bad.** `check_licenses.py`
  fails on any license it cannot place — a new `UNKNOWN` dependency blocks the
  build until its real license is verified and pinned, so metadata gaps cannot
  slip copyleft in silently. The two current overrides are documented with their
  upstream source.
- **Weak-copyleft is classified before the GPL denial.** `lgpl-3.0` and `mpl-2.0`
  contain the substrings the GPL matcher keys on; checking them first prevents a
  false failure on `psycopg` (LGPL) while still denying real GPL/AGPL.
- **Signing without a registry push.** The owner publishes images, so CI signs the
  image *archive* and SBOM as blobs (Cosign keyless via GitHub OIDC) rather than
  pushing and signing a registry ref — integrity evidence travels with the release
  artifacts, nothing is published without the owner.
- **The matrix is enforced, not asserted.** Each SEC-\* row points at a test that
  runs on every PR; a control regression fails the build. The document records the
  mapping, but CI is what keeps it true.

## 3. Accepted findings / deliberate scoping

- **Residual risks R1–R8** are accepted or deferred with rationale in the register
  — chiefly the shared-kernel sandbox (gVisor is the deferred upgrade), the
  permissive default egress allow-list (tightened at deploy), and the node-level
  PID cap on K8s. None is an unmitigated high/high risk.
- **Live-model eval and kind smoke gate at their own cadence**, not per-PR
  (R5) — the deterministic tiers gate every change.
- **Frontend license check runs in CI only** (needs `node_modules`); the backend
  gate (the larger surface) is validated locally and in CI.

## 4. Attack-shaped / robustness checks

The v1.0 posture is verified continuously: the SEC-\* suites (injection framing,
sandbox containment on Docker and K8s, path-traversal, secret-scrub, memory
poisoning, authz matrix, MCP pinning) run on every PR; SAST, CodeQL, gitleaks,
pip-audit, the license gate, Trivy, and Conftest gate the build; and the
booby-trapped-repo scenario is encoded as tests rather than a one-off demo. The
license checker itself is written to fail closed on unrecognized licenses.

## 5. Carry-forward (post-v1)

gVisor runtimeClass for the exec namespace; tighter default egress CIDRs; explicit
hash pins for all bundled models; and promoting the live-model eval + kind smoke
jobs to blocking gates. These are tracked as the deferred/stretch set in
[docs/04](../04-milestones.md).
