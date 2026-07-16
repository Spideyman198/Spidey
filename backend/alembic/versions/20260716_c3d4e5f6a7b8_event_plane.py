"""event plane: event_outbox, run_events (M6)

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-16 12:00:00.000000

The transactional outbox and the durable event spine (docs/08). No FK to runs —
``run_id`` is a correlation id (the runs table lands in M7); events must persist
even for run-less platform facts. Every migration ships a tested downgrade.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(length=26), nullable=False),
        sa.Column("stream_key", sa.String(length=256), nullable=False),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("relayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_outbox")),
        sa.UniqueConstraint("event_id", name=op.f("uq_event_outbox_event_id")),
    )
    op.create_index(
        "ix_event_outbox_unrelayed",
        "event_outbox",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("relayed_at IS NULL"),
    )

    op.create_table(
        "run_events",
        sa.Column("event_id", sa.String(length=26), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("actor", sa.String(length=256), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("span_id", sa.String(length=32), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_run_events")),
    )
    op.create_index(op.f("ix_run_events_run_id"), "run_events", ["run_id"], unique=False)
    op.create_index(
        "ix_run_events_run_occurred", "run_events", ["run_id", "occurred_at"], unique=False
    )


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_table("event_outbox")
