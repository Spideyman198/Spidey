# M1 Security Review

**Date:** 2026-07-10 · **Scope:** identity (users, auth, RBAC, abuse guards), audit plane,
sessions & messages · **Verdict: PASS** (verified live against the compose stack)

## 1. Controls implemented and verified this milestone

| Control (requirement) | Implementation | Verification |
| --- | --- | --- |
| Password hashing (SEC-IAM) | Argon2id via argon2-cffi library defaults (RFC 9106); transparent rehash-on-login when parameters change | `TestArgon2Hasher`; `test_successful_login` rehash path |
| Access tokens | HS256 JWT, 15-min default TTL, pinned `iss`/`aud`, all required claims enforced on decode | `TestJwtIssuer` (tamper, wrong-secret, expired, garbage) |
| Refresh rotation + reuse detection | Rotating single-use refresh tokens (SHA-256 hashed at rest); replay of a consumed token revokes the entire family (OAuth BCP) | `test_refresh_rotation_and_reuse_detection`, `test_reuse_burns_the_whole_family`; live smoke |
| RBAC (admin/developer/viewer) | Strictly ordered roles; route- and tool-level `require_role` dependency; denial audited | `TestRoleMatrix` (every admin route × lower role) |
| Enumeration-safe login | Unknown email verified against a dummy hash so timing and the single error message are identical to a wrong password | `test_unknown_email_is_indistinguishable_from_wrong_password` |
| Brute-force lockout | Per-account consecutive-failure lock (5 → 15 min); a correct password during lockout is still refused | `test_lockout_blocks_correct_password_after_threshold` (live) |
| Rate limiting (SEC-QOS) | Atomic Redis token-bucket per source IP on login (Lua, server-evaluated) | `test_rate_limited_login_is_rejected_before_credential_check` |
| Fail-closed guards | Redis unavailability on the rate limiter/lockout store **raises**, aborting auth — never silently allows | `TestFailClosed` (4 cases) |
| Append-only audit (docs/09 §5) | `audit_log` protected by a DB trigger refusing UPDATE/DELETE, independent of ORM discipline | `test_update_and_delete_are_blocked_at_db_level` (live) |
| Denial evidence durability | Failed-login / lockout / reuse / authz-denied events written on an **independent transaction** that survives the request rollback | `test_failed_login_is_audited_despite_request_failure` (live) |
| Ownership isolation | Sessions/messages scoped to owner; a foreign resource returns **404, not 403** (existence not disclosed, admins included) | `TestOwnershipIsolation` |
| Input validation | Pydantic-strict request schemas; length caps on titles/messages/passwords; NIST-style password policy | `TestValidation`, `test_empty_message_rejected` |
| Secret hygiene | JWT secret is `SecretStr` (never logged); refresh tokens stored only as hashes; PAT-style values redacted by the M0 log scrubber | inherited M0 scrubbing tests |

## 2. Design decisions with security weight

- **Two audit sinks (transactional vs. independent).** Success events (login OK, token refreshed,
  user created) are atomic with their state change — if the action rolls back, so does its audit,
  which is correct. Denial events occur on the exception path, where the request *does* roll back,
  so they use an independent-commit sink. A subtle-but-critical distinction: without it, every
  failed-login and reuse-detection record would vanish with the rollback. Caught and closed during
  implementation; both directions are tested live.
- **Reuse revocation is independent too.** When a consumed refresh token is replayed, the family
  revocation commits on its own transaction before the 401 — a detected replay can never be undone
  by the surrounding rollback.
- **Re-load the user on every request.** The access token is cryptographically sufficient, but the
  auth dependency re-fetches the user so a deactivated/deleted account cannot keep acting until its
  short-lived token expires.
- **`X-Forwarded-For` is ignored** for source IP; only the direct peer is used (client-controlled
  headers must not spoof audit provenance or evade rate limits). A trusted proxy is wired at deploy
  time via uvicorn's `--forwarded-allow-ips`.
- **Admin bootstrap has no config path once live.** The first admin is created by a one-shot CLI
  (`python -m spidey.identity bootstrap-admin`) reading the password from the environment, never
  argv; it refuses on a populated instance.

## 3. Accepted findings / deliberate scoping

- **Access tokens are not revocable before expiry** (stateless JWT). Mitigated by the 15-minute TTL
  and per-request active-user re-check; a token denylist is deferred unless a shorter effective
  revocation window is required.
- **Symmetric (HS256) signing.** One process signs and verifies (ADR-0001); asymmetric keys add
  rotation/management cost for a verifier that doesn't yet exist. Revisit if tokens are ever
  verified out-of-process.
- **GitHub Actions still pinned by tag, not SHA** — unchanged from M0 §3; scheduled for M15.

## 4. Attack-shaped tests added (`tests/security/`, `tests/integration/`)

Authz matrix (route × role), ownership isolation (404-not-403, cross-user message posting),
brute-force lockout defeating a correct password, append-only audit at the DB level, failed-login
evidence surviving rollback, fail-closed guards on Redis outage, JWT tamper/expiry/wrong-secret.

## 5. Carry-forward

M6: MCP boundary controls, provider-key handling. M8+: workspace/filesystem allow-list (SEC-FS).
M9: sandbox red-team review. M15: token-denylist decision, SHA-pinned actions, full SEC-* re-verify.
