# Runbook — Incident Response

Triage for three incident classes: an **outage**, a **security event**, and a
**runaway agent**. First move is always the same: assess blast radius, then
contain, then investigate — the audit log is append-only and survives the
telemetry stack being down.

## 0. Triage (first 5 minutes)

```bash
kubectl -n spidey get pods -l app.kubernetes.io/part-of=spidey
kubectl -n spidey get events --sort-by=.lastTimestamp | tail -30
curl -sf http://localhost:8000/api/v1/health/ready | jq .   # which component?
```

Grafana: **Platform** (API latency/errors, queue depth, DB/Redis health) and
**Agent operations** dashboards. Page-worthy alerts: audit-write failure, cost/hour
anomaly, sandbox policy violations > 0.

## Outage

1. **Localize** — API down, worker backlog, or a datastore? `health/ready` names
   the failing component (database / redis / qdrant).
2. **Datastore down** — Spidey degrades: Qdrant loss disables search but not runs;
   Redis loss stops queues/SSE; Postgres loss is full outage. Restore per
   [backup-restore.md](backup-restore.md).
3. **API errored/crashlooping** — check recent deploy; if correlated, roll back
   ([deploy.md](deploy.md)). Migrations run pre-upgrade, so a failed migration
   blocks the rollout *before* pods change — safe by design.
4. **Worker backlog** — queue depth climbing: confirm KEDA is scaling; if capped,
   raise `maxReplicaCount`. Check for a poison task looping (acks-late + reject-on-
   lost means a crash re-queues).

## Security event

1. **Contain first.** Suspected key compromise → rotate immediately
   ([key-rotation.md](key-rotation.md)). Suspected sandbox escape → cordon the exec
   node pool and scale workers to zero.
2. **Preserve evidence.** The `audit_log` is append-only (DB-trigger enforced) and
   independent of telemetry — pull authn events, authz denials, approvals,
   destructive executions, secret-scan hits, and policy violations for the window.
3. **Scope.** Cross-reference `trace_id` from audit rows into traces/logs. Identify
   affected workspaces/users.
4. **Sandbox specifics.** Exec pods run in `spidey-exec` with a deny-all
   NetworkPolicy, PSS restricted, no SA token — a violation means one of those was
   weakened. Verify the namespace labels and NetworkPolicy are intact:

   ```bash
   kubectl get ns spidey-exec -o jsonpath='{.metadata.labels}'
   kubectl -n spidey-exec get networkpolicy
   ```

## Runaway agent (loops / cost / destructive intent)

1. **Stop the bleeding.** A single run: cancel it (`POST /runs/{id}/cancel`). Broad
   cost spike: trip the global breaker ([cost-runaway-killswitch.md](cost-runaway-killswitch.md)).
2. **Why.** Per-run step/token/cost budgets should have halted it into
   `needs_human` — check whether a budget was mis-set or a tool bypassed the gate.
3. **Blast radius.** Every destructive action passes a durable human-approval gate
   and every commit is on a per-run branch — nothing lands on a default branch
   without approval, so containment is bounded by design.

## After the incident

- [ ] Root cause written up; `trace_id`s and audit references attached.
- [ ] Corrective action tracked (config, budget, policy, or code).
- [ ] If a control failed, add/adjust an alert so it pages next time.
