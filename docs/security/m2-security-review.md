# M2 Security Review

**Date:** 2026-07-10 · **Scope:** workspaces context — `SafeFileSystem`, repository ingestion
(local + GitHub PAT), envelope-encrypted secrets, SSRF-guarded clone, disk quotas ·
**Verdict: PASS** (verified live, including NTFS junction containment on the Windows host)

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Filesystem containment (SEC-FS) | `SafeFileSystem`: two layers — pure `normalize_relative_path` (rejects absolute/drive/UNC/`..`/NUL) + real symlink & junction resolution requiring the target stays under the resolved root | `tests/security/test_safe_filesystem.py`: traversal, absolute, drive, UNC, NUL, POSIX symlink (skipped on Win), **NTFS junction (ran live on Windows)** |
| Path traversal on read and write | Every FS op resolves-then-contains; writes refuse to follow symlinks | `TestReadContainment`, `TestWriteContainment` (out-of-root write leaves the target untouched) |
| Directory walk safety | `os.walk(followlinks=False)`, symlinked subdirs pruned, symlink files skipped, per-entry containment re-checked | `TestWalkAndSize`, `test_symlinked_dir_is_not_walked` |
| Secret encryption at rest (SEC-SEC) | Envelope encryption: HKDF-SHA256 KEK from the env master key wraps a per-secret AES-256-GCM DEK; opaque versioned token | `tests/security/test_encryption.py`: round-trip, nondeterminism, wrong-key, tamper, malformed, unknown-version |
| GitHub PAT never in the clear | Token envelope-encrypted at `create`; decrypted only inside the git adapter; injected as `x-access-token`; scrubbed from every clone error path | `test_token_is_decrypted_before_clone`, `test_create_returns_pending_and_hides_token` (PAT absent from API response) |
| SSRF on clone URL (SEC-SSRF) | HTTPS-only, host allow-list, no embedded credentials, and **DNS resolution rejecting any non-public address** (defeats rebinding at validation time) | `tests/security/test_url_guard.py`: http/ssh rejected, off-allowlist rejected, private/loopback/link-local/`0.0.0.0`/`::1` rejected, mixed public+private rejected |
| Resource quotas (SEC-QOS) | Per-workspace disk quota enforced post-fetch (over-quota → FAILED + tree cleanup); per-file size cap flags oversized files non-indexable | `test_over_quota_fails_and_cleans_up`, manifest size-cap tests |
| Safe failure | Ingestion failures store only a generic message on the workspace; details go to logs/audit; partial trees are removed | `test_clone_failure_marks_failed_and_cleans_up`, `test_corrupt_token_fails_with_safe_message` |
| RBAC + ownership | Create/ingest/delete require `developer`; all reads owner-scoped; a foreign workspace is 404, not 403 | `test_viewer_cannot_create`, `test_ownership_isolation` |
| Audit coverage | workspace create / delete / ingested / ingest-failed recorded | asserted via the audit sink in service tests |

## 2. Design decisions with security weight

- **Two-layer path containment.** The pure policy catches statically-detectable escapes and is
  exhaustively unit-tested with attack strings; the adapter's `resolve()`-then-containment catches
  symlink and NTFS-junction escapes that only real filesystem resolution reveals. Junction
  containment was verified live on the Windows dev host (the test creates a real reparse point with
  `mklink /J` and asserts the read is blocked and the walk excludes it).
- **Documented TOCTOU residual.** `SafeFileSystem` resolves-then-opens, a theoretically racy
  sequence. Within the design the only writer to a workspace is the contained sandbox (M9), so the
  window is unreachable by untrusted code; the sandbox remains the authoritative isolation boundary
  for hostile execution. Recorded in the module docstring, not hidden.
- **Envelope (not direct) encryption.** Per-secret DEKs wrapped by a master-derived KEK mean master
  rotation re-wraps DEKs only, never re-encrypts data — a clean rotation path (runbook, M14). GCM
  authenticates; any tamper fails closed with `DecryptionError`.
- **SSRF guard resolves DNS at validation.** Rejecting hosts that resolve to private/reserved
  addresses blocks using an allow-listed name whose DNS points inward (metadata endpoints, internal
  services), closing the rebinding gap that a name-only allow-list would leave open.
- **`X-Forwarded-For` still ignored** for provenance/rate-limits (carried from M1) — relevant here
  because ingestion is a developer-triggered, audited action.

## 3. Accepted findings / deliberate scoping

- **Local ingestion reads arbitrary host paths** the server process can access. This is the intended
  feature (ingest a local repo) under the v1 operator-trust model (docs/01 §7); the copy skips
  symlinks so a source tree cannot drag in external files, and an allow-list of ingestable base
  directories is a possible future tightening if the trust model narrows.
- **Enqueue-after-commit is not yet atomic.** The create endpoint commits the workspace row then
  enqueues ingestion; a crash in between leaves a `pending` workspace, recoverable via the
  re-ingest endpoint. The transactional outbox (M6) makes this atomic.
- **GitHub PAT stored for re-sync.** Storing user tokens is a liability accepted to support
  incremental re-ingestion; mitigated by envelope encryption, scrubbing, and per-workspace scoping.
  A "transient, do not store" option is a possible future addition.
- **Actions still tag-pinned** (carried from M0 §3; scheduled M15).

## 4. Attack-shaped tests added

SEC-FS traversal/symlink/**junction**/UNC/drive/NUL containment; SSRF scheme/host/private-address
rejection incl. rebinding-shape; envelope-encryption tamper/wrong-key/malformed; PAT absence from
API responses; quota-exceeded cleanup; RBAC + ownership isolation on the workspace API.

## 5. Carry-forward

M3 consumes the file manifest (SHA-256 change detection) for incremental parsing/indexing. M6:
transactional outbox for atomic enqueue, live ingestion progress events. M9: the sandbox that makes
the SafeFileSystem TOCTOU window formally unreachable. M14: master-key rotation runbook.
