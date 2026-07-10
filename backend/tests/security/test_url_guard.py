"""SSRF clone-URL guard (SEC-SSRF)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from spidey.workspaces.infrastructure import UrlPolicyError, validate_clone_url

ALLOWED = ["github.com"]


def _fake_getaddrinfo(addresses: list[str]):
    def _inner(host: str, *_a: object, **_k: object):  # noqa: ARG001
        return [(None, None, None, "", (addr, 0)) for addr in addresses]

    return _inner


class TestSchemeAndHost:
    def test_https_public_host_allowed(self) -> None:
        with patch("socket.getaddrinfo", _fake_getaddrinfo(["140.82.112.3"])):
            assert (
                validate_clone_url("https://github.com/o/r.git", allowed_hosts=ALLOWED)
                == "github.com"
            )

    def test_http_rejected(self) -> None:
        with pytest.raises(UrlPolicyError, match="https"):
            validate_clone_url("http://github.com/o/r.git", allowed_hosts=ALLOWED)

    def test_ssh_scheme_rejected(self) -> None:
        with pytest.raises(UrlPolicyError):
            validate_clone_url("git@github.com:o/r.git", allowed_hosts=ALLOWED)

    def test_host_not_in_allowlist_rejected(self) -> None:
        with (
            patch("socket.getaddrinfo", _fake_getaddrinfo(["140.82.112.3"])),
            pytest.raises(UrlPolicyError, match="allowed"),
        ):
            validate_clone_url("https://evil.example/o/r.git", allowed_hosts=ALLOWED)

    def test_embedded_credentials_rejected(self) -> None:
        with pytest.raises(UrlPolicyError, match="credentials"):
            validate_clone_url("https://user:pw@github.com/o/r.git", allowed_hosts=ALLOWED)


class TestSsrfAddressGuard:
    @pytest.mark.parametrize(
        "private_ip",
        ["127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.169.254", "::1", "0.0.0.0"],
    )
    def test_host_resolving_to_private_address_rejected(self, private_ip: str) -> None:
        # Even an allow-listed host is rejected if DNS returns a private target
        # (defeats DNS-rebinding-style SSRF at validation time).
        with (
            patch("socket.getaddrinfo", _fake_getaddrinfo([private_ip])),
            pytest.raises(UrlPolicyError, match="non-public"),
        ):
            validate_clone_url("https://github.com/o/r.git", allowed_hosts=ALLOWED)

    def test_mixed_public_and_private_rejected(self) -> None:
        with (
            patch("socket.getaddrinfo", _fake_getaddrinfo(["140.82.112.3", "127.0.0.1"])),
            pytest.raises(UrlPolicyError),
        ):
            validate_clone_url("https://github.com/o/r.git", allowed_hosts=ALLOWED)

    def test_unresolvable_host_rejected(self) -> None:
        import socket

        def _boom(*_a: object, **_k: object):
            raise socket.gaierror

        with patch("socket.getaddrinfo", _boom), pytest.raises(UrlPolicyError, match="resolved"):
            validate_clone_url("https://github.com/o/r.git", allowed_hosts=ALLOWED)
