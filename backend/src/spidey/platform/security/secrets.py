"""Secret detection for diffs and generated content (SEC-SECRETS, docs/11).

Where :mod:`scrubbing` silently *redacts* secrets at observability choke points,
this module *detects and reports* them so a write path can refuse: an agent edit
or a run commit that would introduce a credential is blocked outright, not
laundered into the repository with a ``[REDACTED]`` marker.

Detection favors high-confidence shapes (provider-prefixed tokens, key blocks,
URL credentials) — a block is a hard stop for the agent, so false positives are
costlier here than in log redaction. A hit never carries the secret itself:
findings report the kind and line only, so the report is safe to log, event,
and surface to the user.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

# kind → high-confidence pattern. Shapes shared with scrubbing._VALUE_PATTERNS,
# named here because a *finding* must say what it found.
_DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic api key", re.compile(r"\bsk-ant-[a-zA-Z0-9_-]{8,}\b")),
    ("openai-style api key", re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer credential", re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{16,}")),
    ("url-embedded credential", re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@/\s]+@")),
    (
        "hardcoded password assignment",
        # password/passwd/secret assigned a non-trivial literal (8+ chars, no
        # spaces) — quoted string in code or bare value in .env/YAML style.
        re.compile(r"""(?i)\b(?:password|passwd)\s*[:=]\s*["']?[^\s"']{8,}"""),
    ),
)


class SecretFinding(BaseModel):
    """One detected secret. Deliberately excludes the matched value."""

    model_config = ConfigDict(frozen=True)

    kind: str
    line: int  # 1-indexed line within the scanned text


def scan_for_secrets(text: str) -> list[SecretFinding]:
    """Scan ``text`` (a diff, file body, or message) for credential shapes.

    Returns one finding per (kind, line); an empty list means clean. Callers on
    write paths treat any finding as a refusal, not a warning.
    """
    findings: list[SecretFinding] = []
    seen: set[tuple[str, int]] = set()
    for line_no, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _DETECTORS:
            if pattern.search(line) and (kind, line_no) not in seen:
                seen.add((kind, line_no))
                findings.append(SecretFinding(kind=kind, line=line_no))
    return findings


def describe_findings(findings: list[SecretFinding]) -> str:
    """A safe, human-readable refusal message (kinds and lines only)."""
    listed = "; ".join(f"{f.kind} (line {f.line})" for f in findings)
    return f"blocked: content contains secret-shaped values — {listed}"
