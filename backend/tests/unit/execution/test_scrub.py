"""Env scrubbing: inert base only, secrets and non-allow-listed keys dropped."""

from __future__ import annotations

from spidey.execution.domain import scrub_env


def test_fixed_inert_base_is_always_present() -> None:
    env = scrub_env({})
    assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"
    assert env["HOME"] == "/workspace"
    assert env["LANG"] == "C.UTF-8"


def test_non_allowlisted_keys_are_dropped() -> None:
    env = scrub_env({"ANTHROPIC_API_KEY": "x", "DATABASE_URL": "y", "TERM": "xterm"})
    assert "ANTHROPIC_API_KEY" not in env
    assert "DATABASE_URL" not in env
    assert env["TERM"] == "xterm"  # allow-listed inert var passes


def test_secret_shaped_value_is_dropped_even_if_key_allowlisted() -> None:
    # TERM is allow-listed, but a credential-shaped value never forwards.
    env = scrub_env({"TERM": "sk-ant-abcdefghij0123456789"})
    assert "TERM" not in env


def test_caller_cannot_override_path_with_a_secret() -> None:
    env = scrub_env({"PATH": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"})
    assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"  # base retained
