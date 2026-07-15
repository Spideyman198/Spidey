"""code_chunks: is_suspect injection-screen flag (M4)

Revision ID: a1b2c3d4e5f6
Revises: 0029007da215
Create Date: 2026-07-15 10:00:00.000000

Adds the index-time injection-screen result (SEC-PI) to persisted chunks so the
symbol store agrees with the vector payload. Server default false backfills
existing rows. Every migration ships a real, tested downgrade (docs/12 §4).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "0029007da215"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "code_chunks",
        sa.Column(
            "is_suspect",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("code_chunks", "is_suspect")
