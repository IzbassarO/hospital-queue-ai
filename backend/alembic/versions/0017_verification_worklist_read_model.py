"""verification worklist publication read model

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-28 14:00:00

Three tables, kept apart from the measured queue on purpose. `waiting_list_*` is the queue as the Ministry of
Health recorded it and this migration does not touch it: a worklist is a list of records to check, and the product
must never be able to present the difference between the two as "the real queue".

The list ranks the whole formal queue (ghost-queue schema 2); the area table carries `formal_queue_count` beside
the history-quality warning count at every level, so a reader of any single row sees the denominator.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "verification_worklist_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("publication_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("publication_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_code_commit", sa.String(length=40), nullable=False),
        sa.Column("origin", sa.Date(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("decision_owner", sa.String(length=32), nullable=False),
        sa.Column("not_a_decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_publication", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ranking", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("legacy_rule", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("history_quality", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("estimands", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("yield_curve", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("limitations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publication_id", name="uq_verification_worklist_snapshot_publication_id"),
        sa.UniqueConstraint("publication_identity_sha256", name="uq_verification_worklist_snapshot_identity"),
    )
    op.create_index(
        "ix_verification_worklist_snapshot_is_active", "verification_worklist_snapshot", ["is_active"], unique=False
    )
    op.create_index(
        "ux_verification_worklist_snapshot_active",
        "verification_worklist_snapshot",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "verification_worklist_area",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("region_code", sa.String(length=4), nullable=True),
        sa.Column("formal_queue_count", sa.Integer(), nullable=False),
        sa.Column("history_quality_warning_count", sa.Integer(), nullable=False),
        sa.Column("history_quality_warning_share", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["verification_worklist_snapshot.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "level", "code", name="uq_verification_worklist_area_row"),
    )
    op.create_index(
        "ix_verification_worklist_area_snapshot_id", "verification_worklist_area", ["snapshot_id"], unique=False
    )
    op.create_index(
        "ix_verification_worklist_area_level",
        "verification_worklist_area",
        ["snapshot_id", "level", "formal_queue_count"],
        unique=False,
    )
    op.create_table(
        "verification_worklist_item",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("referral_id", sa.BigInteger(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=False),
        sa.Column("region_code", sa.String(length=4), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("days_waited_at_origin", sa.Integer(), nullable=False),
        sa.Column("probability_admitted_30d", sa.Double(), nullable=False),
        sa.Column("probability_admitted_horizon", sa.Double(), nullable=False),
        sa.Column("probability_ever_admitted", sa.Double(), nullable=False),
        sa.Column("observable_curve_end_day", sa.Double(), nullable=False),
        sa.Column("estimate_tier", sa.String(length=24), nullable=False),
        sa.Column("verification_priority_score", sa.Double(), nullable=False),
        sa.Column("comparable_training_at_risk_rows", sa.Integer(), nullable=False),
        sa.Column("history_quality_warning", sa.Boolean(), nullable=False),
        sa.Column("history_quality_reason_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["snapshot_id"], ["verification_worklist_snapshot.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "referral_id", name="uq_verification_worklist_item_row"),
    )
    op.create_index(
        "ix_verification_worklist_item_snapshot_id", "verification_worklist_item", ["snapshot_id"], unique=False
    )
    op.create_index(
        "ix_verification_worklist_item_org_rank",
        "verification_worklist_item",
        ["snapshot_id", "org_code", "rank"],
        unique=False,
    )
    op.create_index(
        "ix_verification_worklist_item_region_rank",
        "verification_worklist_item",
        ["snapshot_id", "region_code", "rank"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_verification_worklist_item_region_rank", table_name="verification_worklist_item")
    op.drop_index("ix_verification_worklist_item_org_rank", table_name="verification_worklist_item")
    op.drop_index("ix_verification_worklist_item_snapshot_id", table_name="verification_worklist_item")
    op.drop_table("verification_worklist_item")
    op.drop_index("ix_verification_worklist_area_level", table_name="verification_worklist_area")
    op.drop_index("ix_verification_worklist_area_snapshot_id", table_name="verification_worklist_area")
    op.drop_table("verification_worklist_area")
    op.drop_index("ux_verification_worklist_snapshot_active", table_name="verification_worklist_snapshot")
    op.drop_index("ix_verification_worklist_snapshot_is_active", table_name="verification_worklist_snapshot")
    op.drop_table("verification_worklist_snapshot")
