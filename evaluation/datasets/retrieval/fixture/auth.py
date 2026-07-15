"""Password hashing and token helpers for the retrieval eval fixture."""

import hashlib
import hmac
import os
import time


def hash_password(password, salt=None):
    """Derive a secure hash from a plaintext password using PBKDF2."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, stored):
    """Check a plaintext password against a previously stored hash."""
    salt_hex, _, digest_hex = stored.partition(":")
    salt = bytes.fromhex(salt_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return hmac.compare_digest(candidate.hex(), digest_hex)


def generate_token(user_id, secret):
    """Produce a signed authentication token for a user session."""
    issued_at = str(int(time.time()))
    payload = f"{user_id}.{issued_at}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"
