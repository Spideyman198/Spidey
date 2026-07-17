"""CommandPolicy — argv admission control (SEC-CMD, ADR-0007).

The single gate that decides whether a command may run *at all*, and with what
network posture. Its rules are deliberately narrow:

- **argv only.** A command is a list of tokens; there is no shell, so there is
  nothing to interpolate, chain (``;`` ``&&`` ``|``), expand (``$()`` ``\\``),
  or redirect. Shell metacharacters in the executable name are rejected outright.
- **allow-list, not deny-list.** Only known-safe base commands run without a
  human. Anything else is not *blocked* — it is ``NEEDS_APPROVAL``, so a human
  can authorize a one-off with eyes open. Fail-closed, never fail-open.
- **network is a privilege.** A tool whose safe use implies fetching (installers)
  is admitted only with an explicit network grant, which itself is approval-gated.

The policy is pure data + a pure function, so its full decision surface is
unit-testable with no container in sight.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from spidey.execution.domain.models import NetworkPolicy


class Admission(StrEnum):
    ALLOWED = "allowed"  # runs with no network, no human
    NEEDS_APPROVAL = "needs_approval"  # a human may authorize (off-list or network)
    DENIED = "denied"  # never runnable as written (malformed / shell attempt)


class CommandDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    admission: Admission
    reason: str
    network: NetworkPolicy = NetworkPolicy.NONE

    @property
    def allowed(self) -> bool:
        return self.admission is Admission.ALLOWED


# Base executables safe to run read-only against untrusted code with no network.
# Test runners, build inspectors, VCS reads — never package installs (those imply
# network + arbitrary postinstall scripts, so they are network-gated below).
_ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        "pytest",
        "python",
        "python3",
        "ruff",
        "mypy",
        "pyright",
        "node",
        "npm",  # only the read/run subcommands below; install is network-gated
        "npx",
        "pnpm",
        "yarn",
        "go",
        "cargo",
        "make",
        "ls",
        "cat",
        "echo",
        "true",
        "git",
    }
)

# Sub-commands that fetch from the network → admissible only with a grant.
_NETWORK_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "npm": frozenset({"install", "ci", "i", "add", "update", "audit"}),
    "pnpm": frozenset({"install", "add", "update"}),
    "yarn": frozenset({"install", "add", "up"}),
    "pip": frozenset({"install", "download"}),
    "go": frozenset({"get", "install", "mod"}),
    "cargo": frozenset({"install", "update", "fetch"}),
    "git": frozenset({"clone", "fetch", "pull", "push", "remote"}),
}

# Characters that only matter to a shell. Their presence in the *executable*
# means the caller is trying to smuggle a shell construct through argv[0].
_SHELL_METACHARS = set(";&|<>$`\n\r\\\"'*?(){}")


class CommandPolicy:
    def __init__(
        self,
        *,
        allowed_commands: frozenset[str] | None = None,
        allow_network_installs: bool = False,
    ) -> None:
        self._allowed = allowed_commands if allowed_commands is not None else _ALLOWED_COMMANDS
        # When installs are pre-authorized for a run, a network subcommand is
        # ALLOWED (with egress proxy) rather than escalated to a human each time.
        self._allow_network = allow_network_installs

    def evaluate(self, argv: list[str]) -> CommandDecision:
        if not argv or not argv[0].strip():
            return CommandDecision(admission=Admission.DENIED, reason="empty command")
        # Screen the raw token (a legit path holds only '/' + name chars); a
        # metacharacter anywhere in argv[0] is a smuggled shell construct.
        if _SHELL_METACHARS & set(argv[0]):
            return CommandDecision(
                admission=Admission.DENIED,
                reason="shell metacharacter in executable — argv only, no shell",
            )
        executable = _basename(argv[0])
        if not executable:
            return CommandDecision(admission=Admission.DENIED, reason="malformed executable")
        if executable not in self._allowed:
            return CommandDecision(
                admission=Admission.NEEDS_APPROVAL,
                reason=f"{executable!r} is not on the allow-list",
            )
        return self._evaluate_network(executable, argv)

    def _evaluate_network(self, executable: str, argv: list[str]) -> CommandDecision:
        subcommands = _NETWORK_SUBCOMMANDS.get(executable)
        if subcommands is not None and _first_subcommand(argv) in subcommands:
            if self._allow_network:
                return CommandDecision(
                    admission=Admission.ALLOWED,
                    reason=f"{executable} network subcommand (pre-authorized egress)",
                    network=NetworkPolicy.EGRESS_PROXY,
                )
            return CommandDecision(
                admission=Admission.NEEDS_APPROVAL,
                reason=f"{executable} needs network — requires approval + egress proxy",
                network=NetworkPolicy.EGRESS_PROXY,
            )
        return CommandDecision(admission=Admission.ALLOWED, reason=f"{executable} is allow-listed")


def _basename(token: str) -> str:
    """The executable name without any path — ``/usr/bin/pytest`` → ``pytest``.
    A path-qualified allow-listed name still resolves to its base for matching."""
    return token.replace("\\", "/").rsplit("/", 1)[-1]


def _first_subcommand(argv: list[str]) -> str | None:
    """The first non-flag token after the executable (``npm ci`` → ``ci``)."""
    for token in argv[1:]:
        if not token.startswith("-"):
            return token
    return None
