"""K8sJobsSandbox — the Kubernetes execution adapter (ADR-0014, docs/12 §2).

The v1 sandbox drives the host Docker socket, which is unavailable and
unacceptable on Kubernetes (a socket mount is node compromise; DinD is
privileged). This second :class:`~spidey.execution.domain.ports.Sandbox` adapter
runs each admitted command as **one Kubernetes Job** in a dedicated, locked-down
namespace — zero changes to agents or policy, exactly as the port promised.

The hardening is in the Job manifest and is not optional:

- **no service-account token** (``automountServiceAccountToken: false``) — the
  workload cannot talk to the API server;
- **restricted pod security** — ``runAsNonRoot``, read-only rootfs, all
  capabilities dropped, no privilege escalation, ``RuntimeDefault`` seccomp;
- **no retries** (``backoffLimit: 0``) — hostile code runs at most once;
- **hard wall-clock kill** (``activeDeadlineSeconds``) and auto-cleanup
  (``ttlSecondsAfterFinished``), plus an explicit delete in ``finally``;
- **resource limits** (CPU, memory) and a single writable workspace mount (a
  PVC subPath) plus an in-pod ``emptyDir`` for ``/tmp`` — nothing else.

Network isolation and the per-pod PID cap are **node/namespace** concerns on
Kubernetes: a ``deny-all`` NetworkPolicy on the exec namespace and the kubelet's
``podPidsLimit`` (both shipped by the Helm chart) enforce what the Docker adapter
did per-container. A crash, timeout, or OOM is an :class:`ExecutionResult`, never
an exception — the caller degrades, it does not crash.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol

from spidey.execution.domain import ExecutionResult, ResourceUsage
from spidey.platform.errors import ValidationFailedError
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from spidey.execution.domain import ExecutionRequest

_logger = get_logger("spidey.execution.k8s")

# Added to the in-container deadline so the Job's activeDeadlineSeconds fires
# after the command's own timeout, letting us read a real (partial) result.
_DEADLINE_GRACE_SECONDS = 5
# Finished Jobs are garbage-collected by the control plane after this, a backstop
# to the explicit delete in case the worker dies mid-run.
_TTL_AFTER_FINISHED_SECONDS = 300


@dataclass(frozen=True, slots=True)
class K8sJobConfig:
    """Placement and identity for exec Jobs (the chart provisions the rest)."""

    image: str
    workspace_pvc_claim: str
    namespace: str = "spidey-exec"
    service_account: str = "spidey-exec"
    workspace_root: str = "/var/lib/spidey/workspaces"
    run_uid: int = 65532
    run_gid: int = 65532
    image_pull_policy: str = "IfNotPresent"
    extra_labels: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True, slots=True)
class RawJobOutcome:
    """The cluster-side result of a Job, before it becomes an ExecutionResult."""

    exit_code: int | None
    timed_out: bool = False
    out_of_memory: bool = False


class JobClient(Protocol):
    """The narrow slice of the Kubernetes API the adapter needs.

    Segregated behind a Protocol so the orchestration and result-mapping in
    :class:`K8sJobsSandbox` are unit-testable with a fake, without a live cluster.
    """

    def create(self, *, namespace: str, manifest: dict[str, Any]) -> None: ...

    def await_completion(
        self, *, namespace: str, name: str, timeout_seconds: int
    ) -> RawJobOutcome: ...

    def logs(self, *, namespace: str, name: str, max_bytes: int) -> tuple[str, bool]: ...

    def delete(self, *, namespace: str, name: str) -> None: ...


def workspace_subpath(workspace_path: str, workspace_root: str) -> str:
    """The PVC subPath for a workspace — its path relative to the shared root.

    The worker and exec Job share the workspaces PVC; the Job mounts only this
    one workspace's subtree. A path outside the root cannot be mounted safely, so
    it is rejected (the caller turns the raised error into a fail-closed result).
    """
    try:
        return str(PurePosixPath(workspace_path).relative_to(PurePosixPath(workspace_root)))
    except ValueError as exc:
        msg = "workspace path is not under the configured workspace root"
        raise ValidationFailedError(
            msg, workspace_path=workspace_path, workspace_root=workspace_root
        ) from exc


def _job_name() -> str:
    """A unique, DNS-1123-safe Job name."""
    return f"spidey-exec-{uuid.uuid4().hex[:12]}"


def build_job_manifest(
    request: ExecutionRequest, config: K8sJobConfig, *, job_name: str
) -> dict[str, Any]:
    """Build the hardened Job manifest for one execution (pure, no API calls)."""
    limits = request.limits
    subpath = workspace_subpath(request.workspace_path, config.workspace_root)
    labels = {
        "app.kubernetes.io/name": "spidey",
        "app.kubernetes.io/component": "sandbox-exec",
        "app.kubernetes.io/managed-by": "spidey-worker",
        **config.extra_labels,
    }
    container_security = {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "runAsNonRoot": True,
        "runAsUser": config.run_uid,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    pod_security = {
        "runAsNonRoot": True,
        "runAsUser": config.run_uid,
        "runAsGroup": config.run_gid,
        "fsGroup": config.run_gid,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    container = {
        "name": "exec",
        "image": config.image,
        "imagePullPolicy": config.image_pull_policy,
        "command": list(request.argv),
        "workingDir": request.workdir,
        "env": [{"name": k, "value": v} for k, v in sorted(request.env.items())],
        "resources": {
            "limits": {"cpu": cpu_millicores(limits.cpus), "memory": f"{limits.memory_mb}Mi"},
            "requests": {"cpu": cpu_millicores(limits.cpus), "memory": f"{limits.memory_mb}Mi"},
        },
        "securityContext": container_security,
        "volumeMounts": [
            {"name": "workspace", "mountPath": request.workdir, "subPath": subpath},
            # An in-pod emptyDir mount target, not a host temp path — S108 N/A.
            {"name": "tmp", "mountPath": "/tmp"},  # noqa: S108  # nosec B108
        ],
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name, "namespace": config.namespace, "labels": labels},
        "spec": {
            "backoffLimit": 0,  # hostile code runs at most once
            "activeDeadlineSeconds": limits.timeout_seconds + _DEADLINE_GRACE_SECONDS,
            "ttlSecondsAfterFinished": _TTL_AFTER_FINISHED_SECONDS,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": config.service_account,
                    "automountServiceAccountToken": False,  # no API-server reach
                    "securityContext": pod_security,
                    "containers": [container],
                    "volumes": [
                        {
                            "name": "workspace",
                            "persistentVolumeClaim": {"claimName": config.workspace_pvc_claim},
                        },
                        {"name": "tmp", "emptyDir": {"sizeLimit": "64Mi"}},
                    ],
                },
            },
        },
    }


def cpu_millicores(cpus: float) -> str:
    """Kubernetes millicpu string for a fractional CPU limit (1.0 -> ``1000m``)."""
    return f"{round(cpus * 1000)}m"


class K8sJobsSandbox:
    """Runs each execution as a hardened Kubernetes Job (satisfies ``Sandbox``)."""

    def __init__(self, *, config: K8sJobConfig, client: JobClient | None = None) -> None:
        self._config = config
        # The real client is built lazily so importing this module (and the API
        # process, which never runs a sandbox) needs no in-cluster kube config.
        self._client = client

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        try:
            return await asyncio.to_thread(self._run_sync, request)
        except Exception:  # a broken API server / bad config must not crash the run
            _logger.exception("k8s_sandbox_run_failed")
            return ExecutionResult(exit_code=None, stderr="sandbox unavailable")

    def _run_sync(self, request: ExecutionRequest) -> ExecutionResult:
        client = self._client or _build_incluster_client()
        namespace = self._config.namespace
        name = _job_name()
        manifest = build_job_manifest(request, self._config, job_name=name)
        client.create(namespace=namespace, manifest=manifest)
        try:
            outcome = client.await_completion(
                namespace=namespace,
                name=name,
                timeout_seconds=request.limits.timeout_seconds + _DEADLINE_GRACE_SECONDS,
            )
            stdout, truncated = client.logs(
                namespace=namespace, name=name, max_bytes=request.limits.max_output_bytes
            )
        finally:
            client.delete(namespace=namespace, name=name)
        killed = outcome.timed_out or outcome.out_of_memory
        return ExecutionResult(
            exit_code=None if killed else outcome.exit_code,
            stdout=stdout,
            timed_out=outcome.timed_out,
            truncated=truncated,
            out_of_memory=outcome.out_of_memory,
            usage=ResourceUsage(),
        )


def _build_incluster_client() -> JobClient:
    # Deferred so the kubernetes client (and its in-cluster config) is imported
    # only when a sandbox actually runs in-cluster — the API never pays for it.
    from spidey.execution.infrastructure.k8s_client import (  # noqa: PLC0415
        KubernetesJobClient,
    )

    return KubernetesJobClient()
