"""Alembic environment: async engine, URL from application Settings.

``target_metadata`` is empty until the first persisted models land (M1);
``alembic upgrade head`` is a clean no-op until then, which lets container
entrypoints run migrations unconditionally from M0.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

# The Alembic env is an entrypoint outside the spidey package, so it may import
# every context directly (unlike the platform kernel). Importing each context's
# ORM models registers them on the shared Base, so autogenerate and migrations
# see the whole schema from one metadata object.
from spidey.codeintel.infrastructure import orm as _codeintel_orm  # noqa: F401
from spidey.identity.infrastructure import orm as _identity_orm  # noqa: F401
from spidey.memory.infrastructure import orm as _memory_orm  # noqa: F401
from spidey.platform import audit as _audit_orm  # noqa: F401
from spidey.platform.config import get_settings
from spidey.platform.db import Base
from spidey.workspaces.infrastructure import orm as _workspaces_orm  # noqa: F401

if TYPE_CHECKING:
    from sqlalchemy import Connection

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a database connection (``--sql`` mode)."""
    context.configure(
        url=get_settings().database_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_dsn, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
