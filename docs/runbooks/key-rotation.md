# Runbook — Key & Secret Rotation

Rotate the three secret classes: the **JWT signing key** (`SPIDEY_AUTH_SECRET_KEY`),
the **encryption master key** (`SPIDEY_ENCRYPTION_MASTER_KEY`, wraps stored GitHub
PATs), and **provider API keys**. All live in the External Secrets store; the chart
never holds secret material.

## Provider API keys (lowest blast radius)

1. Issue a new key with the provider; add it to the secret store under the same
   remote key/property.
2. Trigger a sync (or wait for `refreshInterval`), then restart consumers:

   ```bash
   kubectl -n spidey rollout restart deploy -l app.kubernetes.io/component=worker
   ```

3. Confirm runs still call the provider (a fresh agent run, or the `llm` health
   signal). Revoke the old key once traffic has drained.

## JWT signing key (`SPIDEY_AUTH_SECRET_KEY`)

Rotating this **invalidates all existing access tokens** (HS256). Refresh tokens
are DB-backed and survive, so clients recover on next refresh.

1. Update the secret store with a new 32+ char key; sync.
2. Rolling-restart the API:

   ```bash
   kubectl -n spidey rollout restart deploy/spidey-api
   ```

3. Expect a burst of 401s as old access tokens are rejected; clients refresh and
   recover. Watch the auth-denial rate return to baseline.

## Encryption master key (`SPIDEY_ENCRYPTION_MASTER_KEY`)

This wraps user secrets (GitHub PATs) with envelope encryption (HKDF +
AES-256-GCM). **Rotating it naively makes existing ciphertext undecryptable.** Two
safe paths:

- **Re-encrypt (preferred)**: stand up the new key alongside the old, decrypt
  every stored secret with the old key and re-encrypt with the new, then retire
  the old key. Do this with a one-off maintenance job that reads both keys.
- **Invalidate**: if re-encryption is not feasible, rotate the key and require
  users to re-enter their PATs (existing wrapped secrets become unreadable and are
  purged). Communicate the impact first.

Never rotate the master key without one of these plans — you will lock out stored
credentials.

## After any rotation

- [ ] `health/ready` green; no crash-looping pods.
- [ ] Auth-denial rate back to baseline (JWT rotation).
- [ ] An agent run completes an LLM call (provider-key rotation).
- [ ] A workspace with a stored PAT can still ingest (master-key rotation).
- [ ] The old secret version is revoked/removed from the store.
