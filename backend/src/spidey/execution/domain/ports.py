"""Execution ports — the seam ADR-0007 promises.

``Sandbox`` is deliberately tiny: give it a fully-formed, already-admitted
:class:`ExecutionRequest` and it returns a bounded :class:`ExecutionResult`.
The hardening (network, user, rootfs, cgroups, timeout, output cap) lives in the
adapter; swapping Docker for gVisor/Firecracker or k8s Jobs (post-v1) is an
adapter change, never a caller change. A sandbox *never raises* for a hostile or
failing command — a crash, timeout, or OOM is an ``ExecutionResult``, so the
caller degrades instead of propagating.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from spidey.execution.domain.models import ExecutionRequest, ExecutionResult


class Sandbox(Protocol):
    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        """Run one command in a fresh, disposable, hardened container and return
        its bounded result. Must not raise for command failure/timeout/OOM."""
        ...
