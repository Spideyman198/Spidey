"""Clone-URL validation (SSRF defense, SEC-SSRF).

A repository URL is attacker-influenced input. Before any clone we require:
HTTPS scheme, a host on the configured allow-list, no embedded credentials, and
— after DNS resolution — that every resolved address is publicly routable
(never loopback, private, link-local, or otherwise reserved). This blocks
using a clone to reach internal services or cloud metadata endpoints.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from spidey.platform.errors import SpideyError


class UrlPolicyError(SpideyError):
    """A clone URL violated the SSRF policy."""

    status = 400
    title = "Invalid repository URL"


def _resolved_addresses(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlPolicyError("repository host could not be resolved") from exc
    return [str(info[4][0]) for info in infos]


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_clone_url(url: str, *, allowed_hosts: list[str]) -> str:
    """Validate a clone URL and return its normalized host.

    Performs live DNS resolution and rejects any host that resolves to a
    non-public address, defeating DNS-rebinding-style SSRF attempts at
    validation time.
    """
    parts = urlsplit(url)

    if parts.scheme != "https":
        raise UrlPolicyError("only https repository URLs are permitted")
    if parts.username or parts.password:
        raise UrlPolicyError("credentials must not be embedded in the URL")
    host = parts.hostname
    if not host:
        raise UrlPolicyError("repository URL has no host")

    host = host.lower()
    if host not in {h.lower() for h in allowed_hosts}:
        raise UrlPolicyError(f"host {host!r} is not in the allowed-git-hosts list")

    addresses = _resolved_addresses(host)
    if not addresses or not all(_is_public(addr) for addr in addresses):
        raise UrlPolicyError("repository host resolves to a non-public address")

    return host
