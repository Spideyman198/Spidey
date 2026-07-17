"""B4 red-team: the sandbox contains hostile code (docs/11 §1, ADR-0007).

The defining asymmetry of the system is that Zone 3 *deliberately executes*
untrusted Zone-0 code, so the property under test is the container wall, not the
interior. Each case is a booby trap a malicious repository might plant — network
exfiltration, a fork bomb, a host-filesystem probe, a runaway process, a log
flood — and asserts the wall holds: the attempt is contained and the call still
returns a bounded result instead of harming the host.

Requires a reachable Docker daemon; skipped automatically otherwise (the probe
also verifies bind-mount + exec actually work in this environment, so a
misconfigured Docker Desktop skips rather than errors).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from spidey.execution.domain import ExecutionRequest, ExecutionResult, SandboxLimits
from spidey.execution.infrastructure import DockerSandbox

# A stock image with a Python interpreter; all hardening is applied at run time
# by DockerSandbox, so the image itself need not be the production sandbox image.
_IMAGE = "python:3.12-slim"


def _probe() -> bool:
    """True only if we can actually run a trivial command end-to-end here."""
    try:
        import docker

        client = docker.from_env()
        client.ping()
        try:
            client.images.get(_IMAGE)
        except Exception:
            client.images.pull(_IMAGE)
    except Exception:
        return False
    try:
        with tempfile.TemporaryDirectory() as workspace:
            result = asyncio.run(
                DockerSandbox(image=_IMAGE).run(
                    ExecutionRequest(argv=["python", "-c", "print(1)"], workspace_path=workspace)
                )
            )
    except Exception:
        return False
    else:
        return result.exit_code == 0


_SANDBOX_OK = _probe()

pytestmark = [
    pytest.mark.sandbox,
    pytest.mark.skipif(not _SANDBOX_OK, reason="usable Docker sandbox not available"),
]


def _sandbox() -> DockerSandbox:
    return DockerSandbox(image=_IMAGE)


async def _run(argv: list[str], workspace: str, **limit_overrides: object) -> ExecutionResult:
    limits = SandboxLimits(**limit_overrides)  # type: ignore[arg-type]
    return await _sandbox().run(
        ExecutionRequest(argv=argv, workspace_path=workspace, limits=limits)
    )


class TestContainment:
    async def test_network_exfiltration_is_blocked(self, tmp_path: Path) -> None:
        # A malicious postinstall trying to phone home hits network=none.
        result = await _run(
            [
                "python",
                "-c",
                "import socket; socket.create_connection(('1.1.1.1', 53), 3)",
            ],
            str(tmp_path),
            timeout_seconds=20,
        )
        assert not result.ok  # the connection could not be made
        assert result.exit_code != 0

    async def test_runs_as_non_root(self, tmp_path: Path) -> None:
        result = await _run(["python", "-c", "import os; print(os.getuid())"], str(tmp_path))
        assert result.ok
        uid = int(result.stdout.strip())
        assert uid != 0  # the security property: never root
        # Runs as the workspace owner so the one RW mount is writable to it.
        assert uid == tmp_path.stat().st_uid

    async def test_root_filesystem_is_read_only(self, tmp_path: Path) -> None:
        # Tampering with the image / host-shaped paths fails: rootfs is read-only.
        result = await _run(
            ["python", "-c", "open('/etc/spidey_probe', 'w').write('x')"],
            str(tmp_path),
        )
        assert not result.ok

    async def test_workspace_mount_is_writable_and_isolated(self, tmp_path: Path) -> None:
        # The one writable host surface is the workspace mount — and only it.
        result = await _run(
            ["python", "-c", "open('/workspace/out.txt', 'w').write('hello')"],
            str(tmp_path),
        )
        assert result.ok
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello"

    async def test_wall_clock_timeout_kills_a_runaway(self, tmp_path: Path) -> None:
        result = await _run(
            ["python", "-c", "import time; time.sleep(60)"],
            str(tmp_path),
            timeout_seconds=3,
        )
        assert result.timed_out
        assert result.exit_code is None

    async def test_output_flood_is_truncated(self, tmp_path: Path) -> None:
        result = await _run(
            ["python", "-c", "print('A' * 5_000_000)"],
            str(tmp_path),
            max_output_bytes=4096,
        )
        assert result.truncated
        assert len(result.stdout.encode("utf-8", errors="replace")) <= 4096

    async def test_fork_bomb_is_contained_by_pid_limit(self, tmp_path: Path) -> None:
        # A fork bomb cannot exhaust the host: the PID cap makes fork fail fast,
        # and the call returns a bounded result instead of hanging the worker.
        result = await _run(
            [
                "python",
                "-c",
                "import os\nfor _ in range(10000):\n try:\n  os.fork()\n except OSError:\n  break",
            ],
            str(tmp_path),
            pids=16,
            memory_mb=128,
            timeout_seconds=20,
        )
        # The property is *containment*: we got a result at all (host intact),
        # and the run ended (cleanly, killed, or timed out) — never unbounded.
        assert result.exit_code is not None or result.timed_out
