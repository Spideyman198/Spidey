"""Envelope encryption for user secrets at rest (GitHub PATs).

Scheme (docs/11 §5): a key-encryption key (KEK) is derived from the
env-provided master key via HKDF-SHA256. Each secret gets a fresh random
256-bit data-encryption key (DEK); the plaintext is sealed with the DEK under
AES-256-GCM, and the DEK is wrapped with the KEK under AES-256-GCM. The stored
token carries a version tag so the format — and master-key rotation (re-wrap
DEKs only, never re-encrypt data) — can evolve without a data migration.

Contract: :meth:`encrypt` output is opaque and self-describing; :meth:`decrypt`
raises :class:`DecryptionError` on any tampering, wrong key, or malformed input
— it never returns partially-recovered plaintext.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from spidey.platform.errors import SpideyError

_VERSION = "v1"
_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # GCM standard nonce
_HKDF_INFO = b"spidey.secret.kek.v1"


class DecryptionError(SpideyError):
    """Raised when a secret cannot be authentically decrypted."""

    status = 500
    title = "Decryption failed"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii"))


class SecretCipher:
    """Envelope encryption bound to one master key."""

    def __init__(self, master_key: str) -> None:
        # HKDF turns an arbitrary-length passphrase into a uniform 256-bit KEK.
        # A fixed salt is acceptable here: the master key is already
        # high-entropy (32+ chars, validated in Settings), and per-secret
        # randomness lives in the DEKs and nonces.
        self._kek = HKDF(algorithm=SHA256(), length=_KEY_BYTES, salt=None, info=_HKDF_INFO).derive(
            master_key.encode("utf-8")
        )

    def encrypt(self, plaintext: str) -> str:
        dek = os.urandom(_KEY_BYTES)
        dek_nonce = os.urandom(_NONCE_BYTES)
        wrapped_dek = AESGCM(self._kek).encrypt(dek_nonce, dek, None)

        data_nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(dek).encrypt(data_nonce, plaintext.encode("utf-8"), None)

        return ":".join(
            (_VERSION, _b64e(dek_nonce), _b64e(wrapped_dek), _b64e(data_nonce), _b64e(ciphertext))
        )

    def decrypt(self, token: str) -> str:
        try:
            version, dek_nonce_b, wrapped_b, data_nonce_b, ct_b = token.split(":")
            if version != _VERSION:
                msg = f"unsupported secret version: {version}"
                raise DecryptionError(msg)
            dek = AESGCM(self._kek).decrypt(_b64d(dek_nonce_b), _b64d(wrapped_b), None)
            plaintext = AESGCM(dek).decrypt(_b64d(data_nonce_b), _b64d(ct_b), None)
        except (ValueError, InvalidTag) as exc:
            raise DecryptionError("secret could not be decrypted") from exc
        return plaintext.decode("utf-8")
