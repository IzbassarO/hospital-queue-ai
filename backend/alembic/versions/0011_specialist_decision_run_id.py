"""specialist decisions carry the simulation run they belong to

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-24 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("specialist_decision", sa.Column("run_id", sa.String(length=64), nullable=True))
    op.create_index("ix_specialist_decision_run_id", "specialist_decision", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_specialist_decision_run_id", table_name="specialist_decision")
    op.drop_column("specialist_decision", "run_id")
