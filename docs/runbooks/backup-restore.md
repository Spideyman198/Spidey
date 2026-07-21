# Runbook — Backup & Restore

What to back up, how, and how to restore. Three stateful stores: **Postgres**
(system of record), **Qdrant** (vector index — reconstructible but expensive),
and the **workspaces PVC** (ephemeral working trees).

## What to back up (and priority)

| Store | Priority | Rationale |
| --- | --- | --- |
| Postgres | **critical** | Users, runs, audit log, memory, checkpoints — the source of truth |
| Qdrant | important | Embeddings; reconstructible by re-indexing, but slow to rebuild |
| Workspaces PVC | low | Per-run scratch; runs re-clone from git. Snapshot only if in flight |

## Backup

### Postgres (managed service)

Prefer the provider's automated snapshots (point-in-time recovery on). For an
explicit logical dump:

```bash
kubectl -n spidey run pg-dump --rm -i --restart=Never --image=postgres:16-alpine -- \
  sh -c 'PGPASSWORD=$PW pg_dump -h $HOST -U spidey -d spidey -Fc' \
  > spidey-$(date +%F).dump
```

Store dumps encrypted, off-cluster, with a retention policy (e.g. 30 daily, 12
monthly). **Test restores quarterly** — an untested backup is a hope, not a plan.

### Qdrant

Use Qdrant snapshots (per-collection):

```bash
curl -X POST "$QDRANT/collections/{collection}/snapshots"
# download the returned snapshot artifact to object storage
```

Or accept the rebuild path: on total loss, re-run indexing per workspace.

### Workspaces PVC

Volume snapshots only if runs are in flight and you need continuity; otherwise
skip — runs re-clone from git on retry.

## Restore

1. **Stop writers** — scale API and workers to zero so nothing races the restore:

   ```bash
   kubectl -n spidey scale deploy -l app.kubernetes.io/part-of=spidey --replicas=0
   ```

2. **Postgres** — restore the dump into a clean database:

   ```bash
   pg_restore -h $HOST -U spidey -d spidey --clean --if-exists spidey-<date>.dump
   ```

3. **Qdrant** — recover each collection from its snapshot, or trigger a re-index.

4. **Reconcile schema** — ensure the DB is at the app's expected revision:

   ```bash
   alembic current    # must match the deployed image's head
   ```

5. **Restart and verify**:

   ```bash
   kubectl -n spidey scale deploy/spidey-api --replicas=3
   kubectl -n spidey scale deploy -l app.kubernetes.io/component=worker --replicas=1
   curl -sf http://localhost:8000/api/v1/health/ready | jq .
   ```

## Verification checklist

- [ ] `health/ready` reports all components `ok`.
- [ ] A known run's timeline replays (`GET /runs/{id}/timeline`).
- [ ] The audit log tail is intact and continues appending.
- [ ] A fresh search returns hits (Qdrant reachable / re-indexed).
