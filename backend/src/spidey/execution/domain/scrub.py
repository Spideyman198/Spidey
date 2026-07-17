"""Environment scrubbing (B4): the sandbox inherits nothing by default.

A container that runs hostile code must not receive the host/worker process
environment — it holds provider API keys, the DB DSN, the encryption master key,
and more. The policy is an allow-list, not a deny-list: only a small set of inert
locale/PATH-shaped variables passes through, plus whatever the caller *explicitly*
provides for the task. Anything a caller passes is still screened, so a leaked
secret cannot be forwarded into the sandbox by accident.
"""

from __future__ import annotations

from spidey.platform.security import scan_for_secrets

# Inert variables safe to hand a container; everything else is dropped.
_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"PATH", "HOME", "LANG", "LC_ALL", "TERM", "TZ", "PWD", "SHLVL"}
)

# A minimal, fixed base environment — never derived from the worker's os.environ.
_BASE_ENV: dict[str, str] = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/workspace",
    "LANG": "C.UTF-8",
}


def scrub_env(caller_env: dict[str, str]) -> dict[str, str]:
    """Build the container environment: a fixed inert base plus the caller's
    explicitly-provided, allow-listed, secret-free variables. The host process
    environment is never consulted here — callers pass only what a task needs."""
    result = dict(_BASE_ENV)
    for key, value in caller_env.items():
        if key not in _ALLOWED_KEYS:
            continue
        if scan_for_secrets(f"{key}={value}"):
            continue  # never forward a secret-shaped value, even if allow-listed
        result[key] = value
    return result
