"""specialist decisions of the control centre (alerts and synthetic admission requests)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-23 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "specialist_decision",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("origin", sa.Date(), nullable=False),
        sa.Column("sim_day", sa.Integer(), nullable=False),
        sa.Column("subject_kind", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column("region_code", sa.String(length=4), nullable=True),
        sa.Column("org_code", sa.String(length=8), nullable=True),
        sa.Column("profile_code", sa.String(length=8), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=True),
        sa.Column("api_key_label", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.CheckConstraint("subject_kind IN ('alert', 'patient')", name="ck_specialist_decision_subject_kind"),
        sa.CheckConstraint(
            "action IN ('accept', 'decline', 'clarify', 'confirm', 'postpone')",
            name="ck_specialist_decision_action",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_specialist_decision_created_at", "specialist_decision", ["created_at"], unique=False)
    op.create_index("ix_specialist_decision_origin", "specialist_decision", ["origin"], unique=False)
    op.create_index(
        "ix_specialist_decision_subject", "specialist_decision", ["subject_kind", "subject_id"], unique=False
    )
    op.create_index(
        "ux_specialist_decision_idempotency_key",
        "specialist_decision",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("specialist_decision")
