"""runs.base_commit — git anchor of the run's isolated branch (M8)

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-07-17 12:00:00.000000

The diff API and replay reconstruct "what did this run change" against this
base. Nullable: a workspace-less run never gets one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f7a8b9c0d1e2"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("base_commit", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "base_commit")
