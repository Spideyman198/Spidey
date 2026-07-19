"""long-term memories table (M11)

Revision ID: 9f8e7d6c5b4a
Revises: f7a8b9c0d1e2
Create Date: 2026-07-20 10:00:00.000000

Typed long-term memory records (docs/07). Scope columns (``workspace_id`` /
``user_id``) are the hard recall boundary; the Qdrant ``memories`` collection
holds the vectors, so a delete removes both. Ships a tested downgrade.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9f8e7d6c5b4a"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("distilled_by", sa.String(length=32), nullable=False),
        sa.Column("source_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memories")),
    )
    op.create_index(op.f("ix_memories_user"), "memories", ["user_id"], unique=False)
    op.create_index("ix_memories_scope", "memories", ["kind", "workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_table("memories")
