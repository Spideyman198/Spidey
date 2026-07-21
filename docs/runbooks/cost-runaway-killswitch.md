# Runbook — Cost-Runaway Kill Switch

Stop an LLM cost spike fast, then throttle durably. Spidey meters spend with
per-scope (session/run) rolling token+cost budgets in Redis
(`SPIDEY_LLM_BUDGET_MAX_COST_USD`, `SPIDEY_LLM_BUDGET_MAX_TOKENS`, over
`SPIDEY_LLM_BUDGET_WINDOW_SECONDS`). A scope that would exceed its budget halts
into `needs_human` instead of spending — so the lever is the budget itself.

## 1. Immediate hard stop (seconds)

No new LLM calls happen if no worker is running an agent. Scale the workers that
carry runs to zero:

```bash
kubectl -n spidey scale deploy -l app.kubernetes.io/component=worker --replicas=0
```

In-flight runs are durable (Postgres checkpoints) and resume when workers return —
nothing is lost, spending simply stops. Use this when you do not yet know the
cause.

## 2. Durable throttle (keep serving, cap spend)

To keep the platform up while capping cost, drop the global budget so every scope
trips the gate almost immediately, then restart workers to pick up the new value:

```bash
# Lower the cap in the secret/config source, then:
kubectl -n spidey set env deploy -l app.kubernetes.io/component=worker \
  SPIDEY_LLM_BUDGET_MAX_COST_USD=0.01
kubectl -n spidey rollout restart deploy -l app.kubernetes.io/component=worker
```

New/continuing runs now halt into `needs_human` on their first budgeted call,
visible in the **Cost** and **Agent operations** dashboards (budget-exhaustion
count rises, spend/hour flattens).

## 3. Find and fix the cause

- **Cost dashboard**: spend by model/session/day — which model or session drove
  it? A single looping run, or broad traffic?
- **Single run**: cancel it (`POST /runs/{id}/cancel`); inspect its timeline for a
  loop the fix-retry budget should have caught.
- **Broad**: check for a misconfigured route (an expensive model on a hot role) or
  a caching regression (cache-hit rate dropped on the Cost dashboard).

## 4. Resume normal operation

1. Restore the budget to its normal value in the config source.
2. Restart / scale workers back up:

   ```bash
   kubectl -n spidey set env deploy -l app.kubernetes.io/component=worker \
     SPIDEY_LLM_BUDGET_MAX_COST_USD-       # unset the override
   kubectl -n spidey scale deploy -l app.kubernetes.io/component=worker --replicas=1
   ```

3. Confirm a run completes an LLM call and spend/hour is back to baseline.

## Prevention

- Set `SPIDEY_LLM_BUDGET_MAX_COST_USD` per-scope conservatively for the workload.
- Alert on **cost/hour anomaly** (seed alert) so this runbook is triggered by a
  page, not a bill.
- Keep the cheaper models routed to high-frequency roles (planner/reviewer) and
  reserve premium models for the roles that need them.
