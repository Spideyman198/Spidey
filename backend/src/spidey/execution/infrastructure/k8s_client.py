"""KubernetesJobClient — the live ``JobClient`` over the Kubernetes API.

This is the thin, cluster-facing plumbing behind :class:`K8sJobsSandbox`: create
a Job, poll it to completion (or the wall-clock deadline), read its pod's logs,
and delete it. It is exercised on the live tier / kind CI, not in unit tests —
the adapter's orchestration and result mapping are tested against the ``JobClient``
Protocol with a fake, so this file stays a mechanical translation to the client.

It is imported only lazily (by ``K8sJobsSandbox`` when running in-cluster), so the
API process — which never runs a sandbox — never imports the kubernetes client.
The client models are dynamically generated, so responses are read defensively
(``getattr`` with defaults): a missing field degrades to a conservative outcome
rather than raising, keeping the sandbox non-crashing.
"""

from __future__ import annotations

import time
from typing import Any

from kubernetes import client, config
from kubernetes.client import V1DeleteOptions

from spidey.execution.infrastructure.k8s_sandbox import RawJobOutcome
from spidey.platform.logging import get_logger

_logger = get_logger("spidey.execution.k8s_client")

_POLL_INTERVAL_SECONDS = 1.0


def _as_list(value: Any) -> list[Any]:
    """Coerce a possibly-None dynamic client field into a concrete list."""
    return list(value) if value else []


class KubernetesJobClient:  # pragma: no cover - live cluster plumbing (kind/live tier)
    """Implements ``JobClient`` using the in-cluster Kubernetes configuration."""

    def __init__(self) -> None:
        config.load_incluster_config()
        self._batch: Any = client.BatchV1Api()
        self._core: Any = client.CoreV1Api()

    def create(self, *, namespace: str, manifest: dict[str, Any]) -> None:
        self._batch.create_namespaced_job(namespace=namespace, body=manifest)

    def await_completion(self, *, namespace: str, name: str, timeout_seconds: int) -> RawJobOutcome:
        deadline = time.monotonic() + timeout_seconds + _POLL_INTERVAL_SECONDS
        while time.monotonic() < deadline:
            job = self._batch.read_namespaced_job_status(name, namespace)
            status = getattr(job, "status", None)
            if status is None:
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            if getattr(status, "succeeded", None):
                return RawJobOutcome(exit_code=0)
            if getattr(status, "failed", None):
                return self._failed_outcome(namespace, name, status)
            time.sleep(_POLL_INTERVAL_SECONDS)
        return RawJobOutcome(exit_code=None, timed_out=True)

    def _failed_outcome(self, namespace: str, name: str, status: Any) -> RawJobOutcome:
        for condition in _as_list(getattr(status, "conditions", None)):
            if getattr(condition, "reason", "") == "DeadlineExceeded":
                return RawJobOutcome(exit_code=None, timed_out=True)
        return self._pod_termination(namespace, name)

    def _pod_termination(self, namespace: str, name: str) -> RawJobOutcome:
        pod = self._first_pod(namespace, name)
        if pod is None:
            return RawJobOutcome(exit_code=1)
        pod_status = getattr(pod, "status", None)
        for container in _as_list(getattr(pod_status, "container_statuses", None)):
            terminated = getattr(getattr(container, "state", None), "terminated", None)
            if terminated is not None:
                reason = getattr(terminated, "reason", "")
                return RawJobOutcome(
                    exit_code=getattr(terminated, "exit_code", 1),
                    out_of_memory=reason == "OOMKilled",
                )
        return RawJobOutcome(exit_code=1)

    def logs(self, *, namespace: str, name: str, max_bytes: int) -> tuple[str, bool]:
        pod = self._first_pod(namespace, name)
        pod_name = getattr(getattr(pod, "metadata", None), "name", None)
        if pod_name is None:
            return "", False
        try:
            raw = self._core.read_namespaced_pod_log(name=pod_name, namespace=namespace)
        except Exception:
            _logger.debug("k8s_pod_log_read_failed", job=name)
            return "", False
        text = raw if isinstance(raw, str) else str(raw)
        encoded = text.encode("utf-8", errors="replace")
        truncated = len(encoded) > max_bytes
        return encoded[:max_bytes].decode("utf-8", errors="replace"), truncated

    def delete(self, *, namespace: str, name: str) -> None:
        try:
            self._batch.delete_namespaced_job(
                name=name,
                namespace=namespace,
                body=V1DeleteOptions(propagation_policy="Background"),
            )
        except Exception:
            _logger.debug("k8s_job_delete_noop", job=name)

    def _first_pod(self, namespace: str, name: str) -> Any:
        pods = self._core.list_namespaced_pod(
            namespace=namespace, label_selector=f"job-name={name}"
        )
        items = _as_list(getattr(pods, "items", None))
        return items[0] if items else None
