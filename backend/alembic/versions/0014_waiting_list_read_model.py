"""waiting list publication read model

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-27 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "waiting_list_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("publication_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("publication_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_code_commit", sa.String(length=40), nullable=False),
        sa.Column("origin", sa.Date(), nullable=False),
        sa.Column("outcome_cutoff", sa.DateTime(timezone=False), nullable=False),
        sa.Column("observed_through", sa.Date(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("hospital_count", sa.Integer(), nullable=False),
        sa.Column("waiting_count", sa.Integer(), nullable=False),
        sa.Column("cohort", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("support_thresholds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("limitations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publication_id", name="uq_waiting_list_snapshot_publication_id"),
        sa.UniqueConstraint("publication_identity_sha256", name="uq_waiting_list_snapshot_identity"),
    )
    op.create_index("ix_waiting_list_snapshot_is_active", "waiting_list_snapshot", ["is_active"], unique=False)
    op.create_index(
        "ux_waiting_list_snapshot_active",
        "waiting_list_snapshot",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "waiting_list_hospital",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=False),
        sa.Column("region_code", sa.String(length=4), nullable=False),
        sa.Column("waiting_count", sa.Integer(), nullable=False),
        sa.Column("profile_count", sa.Integer(), nullable=False),
        sa.Column("median_days_waited", sa.Double(), nullable=False),
        sa.Column("max_days_waited", sa.Integer(), nullable=False),
        sa.Column("support_class", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["waiting_list_snapshot.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "org_code", name="uq_waiting_list_hospital_row"),
    )
    op.create_index("ix_waiting_list_hospital_snapshot_id", "waiting_list_hospital", ["snapshot_id"], unique=False)
    op.create_index(
        "ix_waiting_list_hospital_snapshot_count",
        "waiting_list_hospital",
        ["snapshot_id", "waiting_count"],
        unique=False,
    )
    op.create_index(
        "ix_waiting_list_hospital_snapshot_region",
        "waiting_list_hospital",
        ["snapshot_id", "region_code"],
        unique=False,
    )
    op.create_table(
        "waiting_list_referral",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("referral_id", sa.BigInteger(), nullable=False),
        sa.Column("hospitalization_code", sa.String(length=32), nullable=False),
        sa.Column("is_duplicate_code", sa.Boolean(), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=False),
        sa.Column("region_code", sa.String(length=4), nullable=False),
        sa.Column("patient_region_code", sa.String(length=4), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("registration_date", sa.Date(), nullable=False),
        sa.Column("days_waited_at_origin", sa.Integer(), nullable=False),
        sa.Column("observed_status", sa.String(length=32), nullable=False),
        sa.Column("observed_event_date", sa.Date(), nullable=True),
        sa.Column("observed_days_from_origin", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["snapshot_id"], ["waiting_list_snapshot.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "referral_id", name="uq_waiting_list_referral_row"),
    )
    op.create_index("ix_waiting_list_referral_snapshot_id", "waiting_list_referral", ["snapshot_id"], unique=False)
    op.create_index(
        "ix_waiting_list_referral_org_days",
        "waiting_list_referral",
        ["snapshot_id", "org_code", "days_waited_at_origin"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_waiting_list_referral_org_days", table_name="waiting_list_referral")
    op.drop_index("ix_waiting_list_referral_snapshot_id", table_name="waiting_list_referral")
    op.drop_table("waiting_list_referral")
    op.drop_index("ix_waiting_list_hospital_snapshot_region", table_name="waiting_list_hospital")
    op.drop_index("ix_waiting_list_hospital_snapshot_count", table_name="waiting_list_hospital")
    op.drop_index("ix_waiting_list_hospital_snapshot_id", table_name="waiting_list_hospital")
    op.drop_table("waiting_list_hospital")
    op.drop_index("ux_waiting_list_snapshot_active", table_name="waiting_list_snapshot")
    op.drop_index("ix_waiting_list_snapshot_is_active", table_name="waiting_list_snapshot")
    op.drop_table("waiting_list_snapshot")
