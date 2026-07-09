"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Every migration ships a real, tested downgrade (docs/12 §4).
"""

from __future__ import annotations

${imports if imports else "from alembic import op  # noqa: F401\nimport sqlalchemy as sa  # noqa: F401"}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
