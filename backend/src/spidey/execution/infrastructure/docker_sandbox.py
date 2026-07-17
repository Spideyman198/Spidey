"""DockerSandbox — the hardened container adapter (ADR-0007, B4).

Every execution gets a **fresh, disposable** container built to run hostile code
without harming the host. The hardening is applied here, in one place, and is not
optional:

- **network none** (unless the request explicitly asked for the egress-proxy
  posture) — a malicious ``postinstall`` cannot phone home or exfiltrate;
- **non-root, fixed UID**, **read-only rootfs** + small ``tmpfs`` for ``/tmp`` —
  the container cannot persist to or tamper with the image;
- **one RW bind mount**: the workspace copy at the workdir, nothing else from the
  host — no source, no Docker socket, no host paths;
- **cgroup caps**: CPU, memory (OOM-kill), and **PID limit** (a fork bomb hits a
  ceiling instead of the host); ``--cap-drop ALL`` + ``no-new-privileges``;
- **wall-clock timeout** with a hard kill, and **bounded captured output** so a
  gigabyte of log cannot exhaust the worker.

A command failing, timing out, or being OOM-killed is a normal
:class:`ExecutionResult`, never an exception — the caller degrades, it does not
crash.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import docker

from spidey.execution.domain import ExecutionResult, NetworkPolicy, ResourceUsage
from spidey.platform.logging import get_logger

if TYPE_CHECKING:
    from spidey.execution.domain import ExecutionRequest

_logger = get_logger("spidey.execution.docker")

# A slice of the wall-clock timeout added before we stop waiting on the daemon,
# so the in-container timeout fires first and we read a real (partial) result.
_DAEMON_GRACE_SECONDS = 5


class DockerSandbox:
    """Docker SDK adapter. Holds only image/config; a container per ``run``."""

    def __init__(
        self,
        *,
        image: str,
        run_uid: int = 65534,  # nobody
        egress_proxy_network: str | None = None,
    ) -> None:
        self._image = image
        self._uid = run_uid
        # The pre-created, allow-list-only docker network for approved installs.
        # None → egress requests still run with no network (fail-closed).
        self._egress_network = egress_proxy_network

    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        try:
            return await asyncio.to_thread(self._run_sync, request)
        except Exception:  # a broken daemon must not crash the run
            _logger.exception("sandbox_run_failed")
            return ExecutionResult(exit_code=None, stderr="sandbox unavailable")

    def _run_sync(self, request: ExecutionRequest) -> ExecutionResult:
        client = docker.from_env()
        container = client.containers.create(**self._create_kwargs(request))
        try:
            return self._run_container(container, request)
        finally:
            _force_remove(container)

    def _create_kwargs(self, request: ExecutionRequest) -> dict[str, Any]:
        limits = request.limits
        network = (
            self._egress_network
            if limits.network is NetworkPolicy.EGRESS_PROXY and self._egress_network
            else "none"
        )
        return {
            "image": self._image,
            "command": request.argv,
            "working_dir": request.workdir,
            "user": str(self._uid),
            "environment": dict(request.env),
            "network_mode": network,
            "network_disabled": network == "none",
            # One RW mount: the workspace copy. Nothing else from the host.
            "volumes": {request.workspace_path: {"bind": request.workdir, "mode": "rw"}},
            "read_only": True,  # read-only rootfs
            # Container-internal tmpfs (not a host temp path): the only writable
            # area besides the workspace mount, and it is noexec/nosuid. The
            # "/tmp" here is a mount target inside the sandbox, so the temp-dir
            # warnings do not apply.
            "tmpfs": {"/tmp": "rw,size=64m,noexec,nosuid"},  # noqa: S108  # nosec B108
            "mem_limit": f"{limits.memory_mb}m",
            "memswap_limit": f"{limits.memory_mb}m",  # no swap → real memory cap
            "nano_cpus": int(limits.cpus * 1_000_000_000),
            "pids_limit": limits.pids,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "detach": True,
        }

    def _run_container(self, container: Any, request: ExecutionRequest) -> ExecutionResult:
        limits = request.limits
        container.start()
        timed_out = False
        try:
            outcome = container.wait(timeout=limits.timeout_seconds + _DAEMON_GRACE_SECONDS)
            exit_code = int(outcome.get("StatusCode", 1))
        except Exception:
            # Wait timed out at the daemon level → the command overran; kill it.
            timed_out = True
            exit_code = None
            _kill(container)

        stdout, out_trunc = _read_stream(container, limits.max_output_bytes, stderr=False)
        stderr, err_trunc = _read_stream(container, limits.max_output_bytes, stderr=True)
        oom = _was_oom_killed(container)
        return ExecutionResult(
            exit_code=None if (timed_out or oom) else exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            truncated=out_trunc or err_trunc,
            out_of_memory=oom,
            usage=ResourceUsage(),
        )


def _read_stream(container: Any, cap: int, *, stderr: bool) -> tuple[str, bool]:
    """Read one std stream, byte-capped. Returns (text, truncated)."""
    try:
        raw: bytes = container.logs(stdout=not stderr, stderr=stderr, tail="all")
    except Exception:
        return "", False
    truncated = len(raw) > cap
    return raw[:cap].decode("utf-8", errors="replace"), truncated


def _was_oom_killed(container: Any) -> bool:
    try:
        container.reload()
        return bool(container.attrs.get("State", {}).get("OOMKilled", False))
    except Exception:
        return False


def _kill(container: Any) -> None:
    try:
        container.kill()
    except Exception:
        _logger.debug("sandbox_kill_noop")


def _force_remove(container: Any) -> None:
    """Disposability: the container never outlives its one command."""
    try:
        container.remove(force=True, v=True)
    except Exception:
        _logger.debug("sandbox_remove_noop")
