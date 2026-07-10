"""Identity admin CLI: first-run bootstrap of the initial administrator.

    python -m spidey.identity bootstrap-admin --email a@b.com

The password is read from the ``SPIDEY_BOOTSTRAP_PASSWORD`` environment
variable, never a command-line argument (argv is visible in process listings).
Refuses on a populated instance — there is no path to mint an admin via config
once the system is live (see UserService.bootstrap_admin).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from spidey.identity.application import UserService
from spidey.identity.infrastructure import Argon2PasswordHasher
from spidey.identity.infrastructure.repositories import (
    PostgresRefreshTokenRepository,
    PostgresUserRepository,
)
from spidey.platform.audit import AuditLogger
from spidey.platform.config import get_settings
from spidey.platform.db import create_session_factory
from spidey.platform.errors import SpideyError


async def _bootstrap_admin(email: str) -> int:
    password = os.environ.get("SPIDEY_BOOTSTRAP_PASSWORD")
    if not password:
        print("SPIDEY_BOOTSTRAP_PASSWORD must be set", file=sys.stderr)
        return 2

    # Build only the identity context's own dependencies — a context CLI never
    # constructs the global composition root (which would couple it to every
    # other context, breaking the bounded-context independence contract).
    engine = create_async_engine(get_settings().database_dsn)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            service = UserService(
                users=PostgresUserRepository(session),
                refresh_tokens=PostgresRefreshTokenRepository(session),
                hasher=Argon2PasswordHasher(),
                audit=AuditLogger(session),
            )
            try:
                user = await service.bootstrap_admin(email=email, password=password)
            except SpideyError as exc:
                await session.rollback()
                print(f"bootstrap failed: {exc.detail}", file=sys.stderr)
                return 1
            await session.commit()
            print(f"created admin {user.email} ({user.id})")
            return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spidey.identity")
    sub = parser.add_subparsers(dest="command", required=True)
    boot = sub.add_parser("bootstrap-admin", help="create the first admin (first run only)")
    boot.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    if args.command == "bootstrap-admin":
        return asyncio.run(_bootstrap_admin(args.email))
    return 2  # pragma: no cover — argparse enforces a valid subcommand


if __name__ == "__main__":
    sys.exit(main())
