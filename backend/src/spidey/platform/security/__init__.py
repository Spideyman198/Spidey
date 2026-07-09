"""Security primitives shared across contexts.

M0 ships log/output redaction. Password hashing, JWT, and envelope encryption
arrive with the identity context in M1.
"""

from spidey.platform.security.scrubbing import scrub_event_dict, scrub_text

__all__ = ["scrub_event_dict", "scrub_text"]
