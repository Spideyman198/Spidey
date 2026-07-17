# M9 Security Review — Sandboxed Execution (Terminal & Tester)

**Date:** 2026-07-17 · **Scope:** the `execution` bounded context — `CommandPolicy` admission,
`Sandbox` port + `DockerSandbox` hardening, env scrubbing, output secret-scanning, the `terminal.run`
/ `tester.run` tools — i.e. **boundary B4** (worker → sandbox) and **B4r** (sandbox → worker) ·
**Verdict: PASS**

> This is the security-critical milestone (docs/04, docs/11 §1). Zone 3 exists to *deliberately
> execute* untrusted Zone-0 code, so the property defended is the **container wall**, engineered as
> if compromise of the sandbox interior is routine. The red-team checklist below is encoded as an
> executable suite (`tests/security/test_sandbox_containment.py`) that runs each booby trap against a
> **real Docker daemon** and asserts containment; it is gated to run in CI (Linux daemon) and skips
> automatically where no usable daemon is present. A self-probe verifies bind-mount + exec actually
> work before the cases run, so a misconfigured host skips rather than green-washes.

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Argv only — no shell (SEC-CMD) | `CommandPolicy` rejects any shell metacharacter in `argv[0]`; commands are `list[str]` end to end; `DockerSandbox` passes argv as the container command with no shell | `test_policy` shell-attempt denials; `test_sandbox_tools` shell attempt denied even when approved |
| Fail-closed allow-list | Only known-safe base commands are `ALLOWED`; everything else is `NEEDS_APPROVAL` (a human may authorize), never silently blocked or run | `test_policy` allow-list + unknown→needs-approval |
| Network is a privilege | Default `network none`; install subcommands are `NEEDS_APPROVAL` + `EGRESS_PROXY`, and even then only if an egress network is configured (else offline) | `test_policy` network gating; `test_terminal` egress posture |
| Ephemeral, disposable containers | A fresh container per `run`, force-removed in `finally` — no state survives between runs | `DockerSandbox._run_sync` / `_force_remove`; red-team suite reuse |
| No network by default (B4) | `network_mode=none` + `network_disabled` unless an explicit egress grant | **RT-1** exfiltration blocked |
| Non-root always | Container runs as the workspace **owner** UID:GID (never root) — a hostile container is contained by the wall, not the UID number, and this keeps the one RW mount writable with correctly-owned files; a fixed unprivileged UID is the fallback where no owner resolves | **RT-2** `getuid() != 0` and equals the workspace owner |
| Read-only rootfs + tmpfs | `read_only=True`; only `/tmp` (noexec,nosuid, size-capped) and the workspace mount are writable | **RT-3** write to `/etc` fails; **RT-4** workspace writable |
| One RW mount, nothing else | Single workspace bind mount at the workdir; **no host paths, no Docker socket** | `_create_kwargs` volumes; **RT-4** isolation |
| Resource caps (fork bomb / OOM) | cgroup `nano_cpus`, `mem_limit` (+ no swap), **`pids_limit`**; `cap_drop ALL` + `no-new-privileges` | **RT-6** fork bomb contained by PID cap |
| Wall-clock kill | Daemon-side `wait(timeout)`; on overrun the container is killed and the result marked `timed_out` | **RT-5** 60s sleep killed at 3s |
| Bounded captured output | Each std stream byte-capped; `truncated` flag set, never un-truncated | **RT-7** 5 MB flood capped to the limit |
| Env inherits nothing (B4) | `scrub_env` is an allow-list over a fixed inert base; the worker's os.environ is never consulted; secret-shaped values dropped even under allow-listed keys | `test_scrub`; `test_terminal` env scrub |
| Output is hostile input (B4r) | Captured stdout/stderr is secret-scanned/redacted before it can enter a prompt, event, or UI | `test_terminal` secret scrubbed |
| A sandbox never raises | Command failure, timeout, OOM, or a broken daemon are all `ExecutionResult` values | `DockerSandbox.run` try/except; `test_terminal` |
| Approval gate on arbitrary commands | `terminal.run` is `SideEffect.WRITE` → the registry denies it without a resolved, run-scoped human `Approval` (M7 invariant); `tester.run` is `READ` and runs a fixed allow-listed command | `test_sandbox_tools` denied-without-approval / runs-with-approval |

## 2. Red-team checklist

Each case is a booby trap a malicious repository might plant, encoded as an assertion that the wall
holds: the call returns a bounded result instead of harming the host, and the attempt is an auditable
event. Verified in CI against a real Linux Docker daemon.

| # | Attack | Result |
| --- | --- | --- |
| RT-1 | Malicious postinstall opens a socket to a public host (exfiltration / C2) | **Blocked** — `network=none`; connection fails, non-zero exit |
| RT-2 | Privilege assumptions (writes as root, setuid) | **Blocked** — non-root (workspace-owner UID); `no-new-privileges`, `cap-drop ALL` |
| RT-3 | Tamper with the image / host-shaped paths (`/etc/...`) | **Blocked** — read-only rootfs; write fails |
| RT-4 | Reach host files outside the workspace | **Blocked** — only the workspace bind mount is present and writable |
| RT-5 | Runaway process (infinite loop / hang) | **Killed** — wall-clock timeout; `timed_out`, exit `None` |
| RT-6 | Fork bomb (resource exhaustion) | **Contained** — PID cap makes `fork` fail fast; the run returns, host intact |
| RT-7 | Log flood (fill worker disk / memory via output) | **Truncated** — output byte-capped; `truncated` flag set |

## 3. Design decisions with security weight

- **The wall is the product, not the interior.** Every control is applied by `DockerSandbox` at run
  time, in one place, and is not optional. The image is minimal but *untrusted-by-assumption*: even
  if a command fully owns the container interior, `network none` + read-only rootfs + one mount +
  cgroup caps + dropped capabilities mean it owns nothing that matters.
- **Admission is fail-closed and shell-free.** There is no code path from a model-produced string to a
  shell. `CommandPolicy` turns anything unrecognized into a human decision rather than a block, so the
  system is safe *and* usable; a shell-injection attempt is `DENIED` outright and cannot be approved.
- **Two boundaries, both defended.** B4 keeps hostile code from reaching out (network, host FS,
  secrets in env); B4r keeps hostile *output* from reaching in (secret-scan + size cap) before it can
  poison a prompt or leak to the UI.
- **Least privilege for the network too.** Installs are the only reason to grant network, and they get
  an allow-listed egress proxy — never blanket connectivity — and only with an explicit human grant.

## 4. Accepted findings / deliberate scoping

- **Container escape via a kernel 0-day is the residual risk** (documented in ADR-0007 and the risk
  register). Mitigations: no-network default, non-root, dropped caps, no-new-privileges; the `Sandbox`
  port makes a gVisor/Firecracker microVM upgrade an adapter swap, not a redesign (post-v1).
- **TOCTOU on the workspace mount** is out of scope: the only writer to a workspace is the contained
  sandbox itself (carried from the M2 SafeFileSystem review), so the check→open window is not reachable
  by untrusted code.
- **Egress proxy is config, not yet an adapter.** M9 ships the *posture* (a network subcommand runs
  only with a grant, on a pre-created allow-list-only docker network); the proxy service that enforces
  host allow-listing is wired when installs become a first-class flow.
- **Tester graph node is deferred to keep replay stable.** The Terminal/Tester capability ships as
  registry tools the coder can invoke; a dedicated Tester graph node (with the M8 golden-replay
  updated) lands with the M10 debugger loop.
- **Trivy image/filesystem scanning** (docs/11 §3) runs in the container-CI stage against
  `sandbox/Dockerfile`; digest-pinning of the base image is applied by the deploy pipeline.

## 5. Carry-forward

M10 (Debugger, Documenter & PR delivery) consumes the structured `TestReport` to drive a
test→debug→patch loop and adds the Tester graph node. The egress-proxy adapter and gVisor upgrade path
remain the open sandbox items; both are adapter-level changes behind the `Sandbox`/network seams.
