"""Prompt-injection pattern detection (SEC-PI).

A heuristic screen for instruction-injection payloads embedded in untrusted
content — repository files at index time (M4), and long-term memories at write
time (M11). Detection is favored toward recall: a false positive only flags a
chunk `suspect` (it is still indexed, just quarantined at framing time), while a
miss lets an attacker's instructions ride into a prompt. This is a *screen*, not
a guarantee — the primary defense is that ALL retrieved content is data-framed
as inert before entering any prompt (see codeintel.domain.framing).
"""

from __future__ import annotations

import re

# Imperative override phrases — the classic injection openers.
_OVERRIDE = re.compile(
    r"(?i)\b("
    r"ignore\s+(all\s+|the\s+|your\s+|previous\s+|prior\s+|above\s+)"
    r"|disregard\s+(all\s+|the\s+|your\s+|previous\s+|prior\s+|above\s+)"
    r"|forget\s+(everything|all|your|the\s+above|previous)"
    r"|do\s+not\s+(follow|obey|listen)"
    r"|new\s+(instructions?|system\s+prompt|rules?)\s*:"
    r"|override\s+(your|the|all)\s+(instructions?|rules?|prompt)"
    r")"
)

# Role/prompt-boundary spoofing (mimicking chat turns or system frames).
_ROLE_SPOOF = re.compile(
    r"(?im)^\s*("
    r"system\s*:"
    r"|assistant\s*:"
    r"|user\s*:"
    r"|\[/?(system|inst|assistant|user)\]"
    r"|<\|?(im_start|im_end|system|assistant|user)\|?>"
    r")"
)

# Exfiltration / secret-elicitation lures.
_EXFIL = re.compile(
    r"(?i)\b("
    r"reveal\s+(your|the)\s+(system\s+prompt|instructions?|secret|api\s+key)"
    r"|print\s+(your|the)\s+(system\s+prompt|instructions?|secrets?|env(ironment)?\s+variables?)"
    r"|(send|exfiltrate|leak|post)\s+.{0,40}(secret|token|api\s+key|password|credential)"
    r")"
)

_PATTERNS = (_OVERRIDE, _ROLE_SPOOF, _EXFIL)


def looks_like_injection(text: str) -> bool:
    """True when the text carries a known instruction-injection signature."""
    return any(pattern.search(text) for pattern in _PATTERNS)
