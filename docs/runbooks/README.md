# Runbooks

Operational procedures for running Spidey in production (Kubernetes). Each runbook
is a checklist you can follow under pressure — prerequisites, steps, verification,
and rollback.

| Runbook | When to use |
| --- | --- |
| [deploy.md](deploy.md) | Install or upgrade a release; roll back a bad one |
| [backup-restore.md](backup-restore.md) | Back up or restore Postgres, Qdrant, and workspace volumes |
| [key-rotation.md](key-rotation.md) | Rotate the auth signing key, encryption master key, or provider API keys |
| [incident-response.md](incident-response.md) | Triage an outage, a security event, or a runaway agent |
| [cost-runaway-killswitch.md](cost-runaway-killswitch.md) | Stop a cost spike — trip the global LLM circuit breaker |

Conventions: commands assume `kubectl` is pointed at the target cluster and the
release is named `spidey` in namespace `spidey`. Adjust `-n spidey` and the
release name to your environment.
