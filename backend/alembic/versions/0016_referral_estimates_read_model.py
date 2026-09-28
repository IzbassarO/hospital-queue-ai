"""per-referral journey estimates read model

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-28 09:00:00

A separate publication from the waiting list on purpose: the waiting list is measured data whose contract forbids
a model column, these are model output for the same cohort at the same origin. Two tables, joined by referral_id
at read time, so neither publication can quietly acquire the other's guarantees.

The org + refusal index carries the administrative "high refusal risk" ordering of one hospital's queue, which is
otherwise a sort of the whole publication.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "referral_estimate_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("publication_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("publication_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_code_commit", sa.String(length=40), nullable=False),
        sa.Column("origin", sa.Date(), nullable=False),
        sa.Column("outcome_cutoff", sa.DateTime(timezone=False), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("referral_count", sa.Integer(), nullable=False),
        sa.Column("horizons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("admission_window_coverage", sa.Double(), nullable=False),
        sa.Column("source_run", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("selection", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calibration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("estimate_tiers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("abstention_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("degeneracy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attention", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("limitations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publication_id", name="uq_referral_estimate_snapshot_publication_id"),
        sa.UniqueConstraint("publication_identity_sha256", name="uq_referral_estimate_snapshot_identity"),
    )
    op.create_index(
        "ix_referral_estimate_snapshot_is_active", "referral_estimate_snapshot", ["is_active"], unique=False
    )
    op.create_index(
        "ux_referral_estimate_snapshot_active",
        "referral_estimate_snapshot",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "referral_estimate",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("referral_id", sa.BigInteger(), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("estimate_tier", sa.String(length=24), nullable=False),
        sa.Column("similar_training_rows", sa.Integer(), nullable=False),
        sa.Column("admitted_7d", sa.Double(), nullable=False),
        sa.Column("admitted_14d", sa.Double(), nullable=False),
        sa.Column("admitted_30d", sa.Double(), nullable=False),
        sa.Column("refused_30d", sa.Double(), nullable=False),
        sa.Column("window_lower_days", sa.Double(), nullable=True),
        sa.Column("window_upper_days", sa.Double(), nullable=True),
        sa.Column("abstention_reason", sa.String(length=64), nullable=True),
        sa.Column("refusal_attention", sa.Boolean(), nullable=False),
        sa.Column("degenerate_30d", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["referral_estimate_snapshot.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "referral_id", name="uq_referral_estimate_row"),
    )
    op.create_index("ix_referral_estimate_snapshot_id", "referral_estimate", ["snapshot_id"], unique=False)
    op.create_index(
        "ix_referral_estimate_org_refusal",
        "referral_estimate",
        ["snapshot_id", "org_code", "refused_30d"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_referral_estimate_org_refusal", table_name="referral_estimate")
    op.drop_index("ix_referral_estimate_snapshot_id", table_name="referral_estimate")
    op.drop_table("referral_estimate")
    op.drop_index("ux_referral_estimate_snapshot_active", table_name="referral_estimate_snapshot")
    op.drop_index("ix_referral_estimate_snapshot_is_active", table_name="referral_estimate_snapshot")
    op.drop_table("referral_estimate_snapshot")
