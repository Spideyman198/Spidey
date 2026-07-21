"""K8sJobsSandbox: hardened Job manifest + non-crashing orchestration (M14)."""

from __future__ import annotations

from typing import Any

import pytest

from spidey.execution.domain import ExecutionRequest, SandboxLimits
from spidey.execution.infrastructure.k8s_sandbox import (
    K8sJobConfig,
    K8sJobsSandbox,
    RawJobOutcome,
    build_job_manifest,
    cpu_millicores,
    workspace_subpath,
)
from spidey.platform.errors import ValidationFailedError

_CONFIG = K8sJobConfig(
    image="spidey-sandbox:pinned",
    workspace_pvc_claim="spidey-workspaces",
    workspace_root="/var/lib/spidey/workspaces",
    run_uid=65532,
    run_gid=65532,
)


def _request(**overrides: Any) -> ExecutionRequest:
    base: dict[str, Any] = {
        "argv": ["pytest", "-q"],
        "workspace_path": "/var/lib/spidey/workspaces/ws1/repo",
        "workdir": "/workspace",
        "env": {"CI": "1", "A": "b"},
        "limits": SandboxLimits(cpus=2.0, memory_mb=1024, timeout_seconds=60),
    }
    base.update(overrides)
    return ExecutionRequest(**base)


class TestJobManifest:
    def test_hardening_flags(self) -> None:
        m = build_job_manifest(_request(), _CONFIG, job_name="spidey-exec-abc")
        spec = m["spec"]
        pod = spec["template"]["spec"]
        container = pod["containers"][0]
        csec = container["securityContext"]

        assert spec["backoffLimit"] == 0  # hostile code runs at most once
        assert spec["activeDeadlineSeconds"] == 60 + 5  # timeout + grace
        assert spec["ttlSecondsAfterFinished"] == 300
        assert pod["restartPolicy"] == "Never"
        assert pod["automountServiceAccountToken"] is False
        assert pod["serviceAccountName"] == "spidey-exec"
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"]["runAsUser"] == 65532
        assert csec["allowPrivilegeEscalation"] is False
        assert csec["readOnlyRootFilesystem"] is True
        assert csec["runAsNonRoot"] is True
        assert csec["capabilities"]["drop"] == ["ALL"]
        assert csec["seccompProfile"]["type"] == "RuntimeDefault"

    def test_command_env_and_resources(self) -> None:
        m = build_job_manifest(_request(), _CONFIG, job_name="j")
        container = m["spec"]["template"]["spec"]["containers"][0]
        assert container["command"] == ["pytest", "-q"]
        assert container["workingDir"] == "/workspace"
        # env is emitted sorted for a deterministic manifest.
        assert container["env"] == [{"name": "A", "value": "b"}, {"name": "CI", "value": "1"}]
        assert container["resources"]["limits"] == {"cpu": "2000m", "memory": "1024Mi"}
        assert container["resources"]["requests"] == {"cpu": "2000m", "memory": "1024Mi"}
        assert container["image"] == "spidey-sandbox:pinned"

    def test_single_writable_workspace_mount_via_subpath(self) -> None:
        m = build_job_manifest(_request(), _CONFIG, job_name="j")
        pod = m["spec"]["template"]["spec"]
        mounts = {mount["name"]: mount for mount in pod["containers"][0]["volumeMounts"]}
        assert mounts["workspace"]["mountPath"] == "/workspace"
        assert mounts["workspace"]["subPath"] == "ws1/repo"
        assert mounts["tmp"]["mountPath"] == "/tmp"  # noqa: S108
        volumes = {v["name"]: v for v in pod["volumes"]}
        assert volumes["workspace"]["persistentVolumeClaim"]["claimName"] == "spidey-workspaces"
        assert "emptyDir" in volumes["tmp"]

    def test_namespace_and_labels(self) -> None:
        m = build_job_manifest(_request(), _CONFIG, job_name="j")
        assert m["metadata"]["namespace"] == "spidey-exec"
        assert m["metadata"]["labels"]["app.kubernetes.io/component"] == "sandbox-exec"


class TestHelpers:
    def test_subpath_relative_to_root(self) -> None:
        assert (
            workspace_subpath("/var/lib/spidey/workspaces/w/r", "/var/lib/spidey/workspaces")
            == "w/r"
        )

    def test_subpath_rejects_escape(self) -> None:
        with pytest.raises(ValidationFailedError):
            workspace_subpath("/etc/passwd", "/var/lib/spidey/workspaces")

    def test_cpu_millicpu_conversion(self) -> None:
        assert cpu_millicores(1.0) == "1000m"
        assert cpu_millicores(0.5) == "500m"
        assert cpu_millicores(2.0) == "2000m"


class FakeJobClient:
    def __init__(
        self,
        outcome: RawJobOutcome,
        *,
        logs: tuple[str, bool] = ("output", False),
        raise_on_create: bool = False,
    ) -> None:
        self._outcome = outcome
        self._logs = logs
        self._raise_on_create = raise_on_create
        self.created: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def create(self, *, namespace: str, manifest: dict[str, Any]) -> None:
        if self._raise_on_create:
            raise RuntimeError("api server unreachable")
        self.created.append(manifest)

    def await_completion(self, *, namespace: str, name: str, timeout_seconds: int) -> RawJobOutcome:
        return self._outcome

    def logs(self, *, namespace: str, name: str, max_bytes: int) -> tuple[str, bool]:
        return self._logs

    def delete(self, *, namespace: str, name: str) -> None:
        self.deleted.append(name)


class TestRun:
    async def test_success_maps_to_result(self) -> None:
        client = FakeJobClient(RawJobOutcome(exit_code=0), logs=("all good", False))
        sandbox = K8sJobsSandbox(config=_CONFIG, client=client)
        result = await sandbox.run(_request())
        assert result.exit_code == 0
        assert result.ok
        assert result.stdout == "all good"
        assert len(client.created) == 1
        assert len(client.deleted) == 1  # Job is always cleaned up

    async def test_timeout_maps_to_killed_result(self) -> None:
        client = FakeJobClient(RawJobOutcome(exit_code=None, timed_out=True))
        result = await K8sJobsSandbox(config=_CONFIG, client=client).run(_request())
        assert result.exit_code is None
        assert result.timed_out is True

    async def test_oom_maps_to_killed_result(self) -> None:
        client = FakeJobClient(RawJobOutcome(exit_code=137, out_of_memory=True))
        result = await K8sJobsSandbox(config=_CONFIG, client=client).run(_request())
        assert result.exit_code is None  # killed → no trustworthy exit code
        assert result.out_of_memory is True

    async def test_nonzero_exit_is_preserved(self) -> None:
        client = FakeJobClient(RawJobOutcome(exit_code=1))
        result = await K8sJobsSandbox(config=_CONFIG, client=client).run(_request())
        assert result.exit_code == 1
        assert not result.ok

    async def test_truncation_flag_flows_through(self) -> None:
        client = FakeJobClient(RawJobOutcome(exit_code=0), logs=("cut", True))
        result = await K8sJobsSandbox(config=_CONFIG, client=client).run(_request())
        assert result.truncated is True

    async def test_api_failure_is_never_raised(self) -> None:
        client = FakeJobClient(RawJobOutcome(exit_code=0), raise_on_create=True)
        result = await K8sJobsSandbox(config=_CONFIG, client=client).run(_request())
        assert result.exit_code is None
        assert result.stderr == "sandbox unavailable"

    async def test_bad_workspace_path_fails_closed(self) -> None:
        client = FakeJobClient(RawJobOutcome(exit_code=0))
        sandbox = K8sJobsSandbox(config=_CONFIG, client=client)
        result = await sandbox.run(_request(workspace_path="/etc"))
        assert result.exit_code is None
        assert result.stderr == "sandbox unavailable"
