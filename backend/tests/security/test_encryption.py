"""Envelope encryption for secrets at rest (SEC-SEC)."""

from __future__ import annotations

import pytest

from spidey.platform.security import DecryptionError, SecretCipher

MASTER = "a-master-key-of-at-least-32-characters-length"


class TestRoundTrip:
    def test_encrypt_decrypt(self) -> None:
        cipher = SecretCipher(MASTER)
        token = cipher.encrypt("ghp_secret_pat_value")
        assert cipher.decrypt(token) == "ghp_secret_pat_value"

    def test_ciphertext_hides_plaintext(self) -> None:
        cipher = SecretCipher(MASTER)
        token = cipher.encrypt("ghp_secret_pat_value")
        assert "ghp_secret_pat_value" not in token
        assert token.startswith("v1:")

    def test_nondeterministic(self) -> None:
        cipher = SecretCipher(MASTER)
        assert cipher.encrypt("same") != cipher.encrypt("same")

    def test_unicode_secret(self) -> None:
        cipher = SecretCipher(MASTER)
        secret = "tökén-“quoted”-🔑"
        assert cipher.decrypt(cipher.encrypt(secret)) == secret


class TestTamperingAndKeys:
    def test_wrong_master_key_fails(self) -> None:
        token = SecretCipher(MASTER).encrypt("secret")
        with pytest.raises(DecryptionError):
            SecretCipher("a-different-master-key-also-32-characters").decrypt(token)

    def test_tampered_ciphertext_fails(self) -> None:
        cipher = SecretCipher(MASTER)
        token = cipher.encrypt("secret")
        head, tail = token.rsplit(":", 1)
        flipped = "A" if tail[0] != "A" else "B"
        with pytest.raises(DecryptionError):
            cipher.decrypt(f"{head}:{flipped}{tail[1:]}")

    def test_malformed_token_fails(self) -> None:
        with pytest.raises(DecryptionError):
            SecretCipher(MASTER).decrypt("not-a-valid-token")

    def test_unknown_version_fails(self) -> None:
        with pytest.raises(DecryptionError):
            SecretCipher(MASTER).decrypt("v9:a:b:c:d")
