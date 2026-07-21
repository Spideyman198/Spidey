# Runbook — Deploy & Rollback

Install or upgrade the Spidey release, and roll back a bad deploy. Migrations run
as a pre-upgrade Alembic Job, so app pods never race the schema.

## Prerequisites

- `kubectl` and `helm` (v3.16+) pointed at the target cluster.
- The app image pushed to the registry (`ghcr.io/spideyman198/spidey:<tag>`),
  built once and promoted across environments.
- Secrets available: either the External Secrets Operator is installed and the
  `ClusterSecretStore` is reachable, or a Secret named `spidey-secrets` exists.
- A `ReadWriteMany` StorageClass for the workspaces PVC (EFS/Filestore/NFS).

## Deploy (install or upgrade)

1. Review the diff against the running release:

   ```bash
   helm diff upgrade spidey deploy/helm/spidey -n spidey -f values-prod.yaml
   ```

2. Apply. The pre-upgrade migration Job runs first and must succeed before pods roll:

   ```bash
   helm upgrade --install spidey deploy/helm/spidey -n spidey \
     -f values-prod.yaml --set image.tag=<tag> --wait --timeout 10m
   ```

3. Verify:

   ```bash
   kubectl -n spidey rollout status deploy/spidey-api
   kubectl -n spidey get pods -l app.kubernetes.io/part-of=spidey
   helm test spidey -n spidey        # API health + restricted sandbox pod
   ```

   Then hit readiness (all components `ok`):

   ```bash
   kubectl -n spidey port-forward svc/spidey-api 8000:8000 &
   curl -sf http://localhost:8000/api/v1/health/ready | jq .
   ```

## Rollback

Every migration ships a tested `downgrade`, so a rollback is Helm + Alembic:

1. Roll the release back to the previous revision:

   ```bash
   helm history spidey -n spidey
   helm rollback spidey <PREVIOUS_REVISION> -n spidey --wait
   ```

2. If the bad release included a **schema migration**, downgrade it explicitly
   (Helm rollback does not run Alembic down):

   ```bash
   kubectl -n spidey run spidey-downgrade --rm -i --restart=Never \
     --image=ghcr.io/spideyman198/spidey:<previous-tag> \
     --env-from... -- alembic downgrade -1
   ```

   Only downgrade when the new schema is incompatible with the old code; a
   backward-compatible migration can stay.

3. Verify readiness and `helm test` as above.

## Notes

- **KEDA**: worker autoscaling needs the KEDA operator installed cluster-wide
  (`keda.enabled=true`). Without it, workers run at their static `replicas`.
- **Exec nodes**: set the kubelet `--pod-max-pids` on the node pool that runs the
  `spidey-exec` namespace — the per-pod PID cap cannot be set in the Job manifest.
- **First install**: create the bootstrap admin once (see the app README) after
  the API is ready.
