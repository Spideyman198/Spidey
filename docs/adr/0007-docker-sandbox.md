# ADR-0007: Ephemeral Docker containers as the execution sandbox

**Status:** Accepted · 2026-07-09

## Context

The agent must run commands and tests on **untrusted repositories** (FR-4.1) — the highest-risk
capability in the system. Threats: host compromise via malicious build scripts, secret exfiltration,
resource exhaustion, lateral movement.

## Decision

Every execution gets a fresh container from a hardened image: network `none` by default, non-root
fixed UID, read-only rootfs + tmpfs, single RW bind mount of the workspace copy, cgroup
CPU/memory/PID limits, wall-clock timeout, bounded captured output, scrubbed environment. Managed
via the Docker SDK behind a `Sandbox` port; command admission via `CommandPolicy` (argv-only,
typed-arg allow-list; off-list or network-enabled runs require human approval). The worker never
mounts the Docker socket into sandboxes.

## Alternatives considered

- **gVisor / Firecracker microVMs** — stronger isolation (kernel attack surface), but heavy setup
  and poor Windows-dev-host ergonomics; the `Sandbox` port makes this a planned upgrade path
  (post-v1), not a redesign. Deferred.
- **Subprocess with OS-level restrictions** — no meaningful containment for hostile code,
  non-portable (no seccomp/namespaces on Windows). Rejected.
- **Remote execution service (e.g. cloud runners)** — conflicts with self-hosted posture and adds
  egress of user code. Rejected for v1.

## Consequences

- (+) Strong practical isolation at library-level implementation cost; per-execution disposability
  makes state contamination between runs impossible.
- (−) Container escape via kernel vulnerabilities remains the residual risk — documented in the risk
  register; mitigated by no-network default, non-root, and the gVisor upgrade path.
- (−) Docker becomes a hard runtime dependency for execution features (accepted in doc 01 §7);
  cold-start latency (~1s) is acceptable for test/command workloads.
- (−) Dependency installs need network → explicit approval + egress-proxied allow-listed hosts,
  never blanket network access.
