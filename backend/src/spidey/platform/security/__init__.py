"""Security primitives shared across contexts.

Redaction (M0), envelope encryption for secrets at rest (M2), prompt-injection
screening (M6), secret detection for write paths (M8). Password hashing and JWT
are identity-context concerns and live there.
"""

from spidey.platform.security.encryption import DecryptionError, SecretCipher
from spidey.platform.security.injection import looks_like_injection
from spidey.platform.security.scrubbing import scrub_event_dict, scrub_text
from spidey.platform.security.secrets import (
    SecretFinding,
    describe_findings,
    scan_for_secrets,
)

__all__ = [
    "DecryptionError",
    "SecretCipher",
    "SecretFinding",
    "describe_findings",
    "looks_like_injection",
    "scan_for_secrets",
    "scrub_event_dict",
    "scrub_text",
]
