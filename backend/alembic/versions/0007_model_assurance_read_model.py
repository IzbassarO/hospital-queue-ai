"""model assurance publication read model

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-22 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_assurance_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("assurance_id", sa.String(length=128), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("assurance_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_code_commit", sa.String(length=40), nullable=False),
        sa.Column("ml_freeze_status", sa.String(length=64), nullable=False),
        sa.Column("product_contract_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("capability_count", sa.Integer(), nullable=False),
        sa.Column("failed_evidence_history", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("claim_boundaries", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("monitoring_expectations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("freshness_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assurance_id", name="uq_model_assurance_snapshot_assurance_id"),
        sa.UniqueConstraint("assurance_identity_sha256", name="uq_model_assurance_snapshot_identity"),
    )
    op.create_index(
        "ix_model_assurance_snapshot_is_active",
        "model_assurance_snapshot",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "ux_model_assurance_snapshot_active",
        "model_assurance_snapshot",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "model_assurance_capability",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("capability_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("evidence_status", sa.String(length=16), nullable=False),
        sa.Column("acceptance_verdict", sa.String(length=32), nullable=False),
        sa.Column("product_consumption_status", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column("scientific_identity_sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_identity", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("dataset_identity_sha256", sa.String(length=64), nullable=True),
        sa.Column("config_identity_sha256", sa.String(length=64), nullable=True),
        sa.Column("code_identity_sha256", sa.String(length=64), nullable=True),
        sa.Column("model_identity", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("estimand_id", sa.Text(), nullable=True),
        sa.Column("calibration_identity", sa.Text(), nullable=True),
        sa.Column("hierarchy_identity", sa.Text(), nullable=True),
        sa.Column("pressure_provider_identity", sa.Text(), nullable=True),
        sa.Column("prioritization_identity", sa.Text(), nullable=True),
        sa.Column("scenario_identity", sa.Text(), nullable=True),
        sa.Column("decision_alternative_identity", sa.Text(), nullable=True),
        sa.Column("human_review_required", sa.Boolean(), nullable=False),
        sa.Column("autonomous_action", sa.Boolean(), nullable=False),
        sa.Column("capacity_checked", sa.Boolean(), nullable=False),
        sa.Column("causal_effect_claimed", sa.Boolean(), nullable=False),
        sa.Column("serving_claim", sa.Boolean(), nullable=False),
        sa.Column("physical_feasibility_status", sa.String(length=32), nullable=False),
        sa.Column("promotion_status", sa.String(length=32), nullable=False),
        sa.Column("freshness_state", sa.String(length=16), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["model_assurance_snapshot.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "capability_id", name="uq_model_assurance_capability_snapshot_id"),
    )
    op.create_index(
        "ix_model_assurance_capability_snapshot_id",
        "model_assurance_capability",
        ["snapshot_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_model_assurance_capability_snapshot_id", table_name="model_assurance_capability")
    op.drop_table("model_assurance_capability")
    op.drop_index("ux_model_assurance_snapshot_active", table_name="model_assurance_snapshot")
    op.drop_index("ix_model_assurance_snapshot_is_active", table_name="model_assurance_snapshot")
    op.drop_table("model_assurance_snapshot")
