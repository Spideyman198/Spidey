"""CommandPolicy admission: allow-list, shell-attempt denial, network gating."""

from __future__ import annotations

from spidey.execution.domain import Admission, CommandPolicy, NetworkPolicy


def _policy(*, installs: bool = False) -> CommandPolicy:
    return CommandPolicy(allow_network_installs=installs)


class TestAllowList:
    def test_allow_listed_command_runs_without_network(self) -> None:
        decision = _policy().evaluate(["pytest", "-q", "tests/"])
        assert decision.admission is Admission.ALLOWED
        assert decision.network is NetworkPolicy.NONE

    def test_path_qualified_executable_resolves_to_basename(self) -> None:
        assert _policy().evaluate(["/usr/local/bin/pytest"]).allowed

    def test_unknown_command_needs_approval_not_denied(self) -> None:
        # Fail-closed but not fail-brittle: a human can still authorize a one-off.
        decision = _policy().evaluate(["rm", "-rf", "/"])
        assert decision.admission is Admission.NEEDS_APPROVAL

    def test_empty_command_is_denied(self) -> None:
        assert _policy().evaluate([]).admission is Admission.DENIED
        assert _policy().evaluate([""]).admission is Admission.DENIED


class TestShellAttempts:
    def test_shell_metacharacters_in_executable_are_denied(self) -> None:
        for argv in (
            ["pytest; rm -rf /"],
            ["sh -c 'curl evil'"],
            ["bash|nc"],
            ["$(whoami)"],
            ["a && b"],
            ["python\nimport os"],
        ):
            assert _policy().evaluate(argv).admission is Admission.DENIED, argv

    def test_metacharacters_as_later_args_are_not_the_executable_gate(self) -> None:
        # A ';' in a later arg is passed literally to argv (no shell parses it),
        # so admission turns only on the executable being allow-listed.
        decision = _policy().evaluate(["echo", "a; b"])
        assert decision.admission is Admission.ALLOWED


class TestNetworkGating:
    def test_install_subcommand_needs_approval_by_default(self) -> None:
        decision = _policy().evaluate(["npm", "install"])
        assert decision.admission is Admission.NEEDS_APPROVAL
        assert decision.network is NetworkPolicy.EGRESS_PROXY

    def test_install_allowed_when_preauthorized_with_egress_proxy(self) -> None:
        decision = _policy(installs=True).evaluate(["npm", "ci"])
        assert decision.admission is Admission.ALLOWED
        assert decision.network is NetworkPolicy.EGRESS_PROXY

    def test_non_network_subcommand_of_network_tool_runs_offline(self) -> None:
        decision = _policy().evaluate(["npm", "run", "test"])
        assert decision.admission is Admission.ALLOWED
        assert decision.network is NetworkPolicy.NONE

    def test_git_read_runs_offline_but_clone_needs_network(self) -> None:
        assert _policy().evaluate(["git", "status"]).network is NetworkPolicy.NONE
        clone = _policy().evaluate(["git", "clone", "https://x/y"])
        assert clone.admission is Admission.NEEDS_APPROVAL
