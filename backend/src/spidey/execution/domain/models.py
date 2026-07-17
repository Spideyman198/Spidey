"""Execution domain models (M9): what runs, under what limits, and what came back.

The most dangerous capability in the system runs against *untrusted repositories*
(FR-4.1), so every value here is shaped to make the safe thing the only thing:
commands are argv arrays (never shell strings), limits are always present (a
request cannot omit them), and results carry a truncation flag so a bounded
capture is never mistaken for complete output.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class NetworkPolicy(StrEnum):
    """Container network posture. ``NONE`` is the default and the safe case."""

    NONE = "none"  # no network namespace connectivity (default, B4)
    EGRESS_PROXY = "egress_proxy"  # approved installs via the allow-listed proxy only


class SandboxLimits(BaseModel):
    """Hard resource ceilings for one execution. Every field has a safe default;
    a request always carries limits, so there is no unbounded run."""

    model_config = ConfigDict(frozen=True)

    cpus: float = Field(default=1.0, gt=0, le=8)
    memory_mb: int = Field(default=512, ge=64, le=8192)
    pids: int = Field(default=256, ge=16, le=4096)
    timeout_seconds: int = Field(default=120, ge=1, le=1800)
    max_output_bytes: int = Field(default=1_000_000, ge=1024, le=16_000_000)
    network: NetworkPolicy = NetworkPolicy.NONE


class ExecutionRequest(BaseModel):
    """One admitted command to run inside the sandbox against a workspace tree."""

    model_config = ConfigDict(frozen=True)

    argv: list[str] = Field(min_length=1)
    workspace_path: str  # host path bind-mounted RW at the container workdir
    workdir: str = "/workspace"
    env: dict[str, str] = Field(default_factory=dict[str, str])
    limits: SandboxLimits = Field(default_factory=SandboxLimits)


class ResourceUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    wall_seconds: float = 0.0


class ExecutionResult(BaseModel):
    """The bounded, safe-to-surface outcome of one execution.

    ``exit_code`` is None when the run was killed (timeout/OOM). ``timed_out``
    and ``truncated`` are explicit so a consumer never mistakes a capped capture
    or a killed process for a clean, complete result.
    """

    model_config = ConfigDict(frozen=True)

    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    truncated: bool = False
    out_of_memory: bool = False
    usage: ResourceUsage = Field(default_factory=ResourceUsage)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0
