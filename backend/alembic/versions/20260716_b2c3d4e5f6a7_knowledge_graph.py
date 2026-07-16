"""knowledge graph: code_references, graph_nodes, graph_edges (M5)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-16 09:00:00.000000

Reference rows are captured per file at parse time; nodes/edges are the resolved
graph rebuilt from them inside the index transaction (ADR-0003). Every migration
ships a real, tested downgrade (docs/12 §4).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("from_qualified_name", sa.String(length=1024), nullable=False),
        sa.Column("target_name", sa.String(length=512), nullable=False),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_code_references_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_references")),
    )
    op.create_index(
        op.f("ix_code_references_workspace_id"),
        "code_references",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_code_references_ws_path", "code_references", ["workspace_id", "path"], unique=False
    )

    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("qualified_name", sa.String(length=1024), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_graph_nodes_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_nodes")),
        sa.UniqueConstraint(
            "workspace_id", "path", "qualified_name", name="uq_graph_nodes_ws_path_qn"
        ),
    )
    op.create_index(
        op.f("ix_graph_nodes_workspace_id"), "graph_nodes", ["workspace_id"], unique=False
    )
    op.create_index("ix_graph_nodes_ws_name", "graph_nodes", ["workspace_id", "name"], unique=False)

    op.create_table(
        "graph_edges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("src_id", sa.Uuid(), nullable=False),
        sa.Column("dst_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_graph_edges_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["src_id"],
            ["graph_nodes.id"],
            name=op.f("fk_graph_edges_src_id_graph_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dst_id"],
            ["graph_nodes.id"],
            name=op.f("fk_graph_edges_dst_id_graph_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_edges")),
    )
    op.create_index(
        op.f("ix_graph_edges_workspace_id"), "graph_edges", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_graph_edges_ws_src_kind",
        "graph_edges",
        ["workspace_id", "src_id", "kind"],
        unique=False,
    )
    op.create_index(
        "ix_graph_edges_ws_dst_kind",
        "graph_edges",
        ["workspace_id", "dst_id", "kind"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    op.drop_table("code_references")
