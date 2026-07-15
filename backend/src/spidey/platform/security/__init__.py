"""Security primitives shared across contexts.

Redaction (M0), envelope encryption for secrets at rest (M2). Password hashing
and JWT are identity-context concerns and live there.
"""

from spidey.platform.security.encryption import DecryptionError, SecretCipher
from spidey.platform.security.injection import looks_like_injection
from spidey.platform.security.scrubbing import scrub_event_dict, scrub_text

__all__ = [
    "DecryptionError",
    "SecretCipher",
    "looks_like_injection",
    "scrub_event_dict",
    "scrub_text",
]
