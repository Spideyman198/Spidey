"""Helpers for extracting request metadata used in audit records."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request


def client_ip(request: Request) -> str | None:
    """Direct peer address only.

    ``X-Forwarded-For`` is deliberately ignored: it is client-controlled and
    trusting it unconditionally lets an attacker spoof the source of audit
    records and evade per-IP rate limiting. A trusted reverse proxy is
    configured at deploy time via uvicorn's ``--forwarded-allow-ips`` /
    ProxyHeadersMiddleware, which rewrites ``request.client`` safely.
    """
    return request.client.host if request.client is not None else None


def request_id(request: Request) -> str | None:
    return request.headers.get("x-request-id")
