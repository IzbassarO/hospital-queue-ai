"""operational intelligence publication read model

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-22 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operational_intelligence_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("publication_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("publication_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("assurance_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_code_commit", sa.String(length=40), nullable=False),
        sa.Column("current_origin", sa.Date(), nullable=False),
        sa.Column("freshness_state", sa.String(length=16), nullable=False),
        sa.Column("publication_status", sa.String(length=16), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("forecast_count", sa.Integer(), nullable=False),
        sa.Column("signal_count", sa.Integer(), nullable=False),
        sa.Column("source_provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("limitations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publication_id", name="uq_operational_intelligence_snapshot_publication_id"),
        sa.UniqueConstraint(
            "publication_identity_sha256",
            name="uq_operational_intelligence_snapshot_identity",
        ),
    )
    op.create_index(
        "ix_operational_intelligence_snapshot_is_active",
        "operational_intelligence_snapshot",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "ux_operational_intelligence_snapshot_active",
        "operational_intelligence_snapshot",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "operational_forecast",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("series_id", sa.String(length=64), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("origin", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("horizon", sa.SmallInteger(), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=True),
        sa.Column("region_code", sa.String(length=4), nullable=True),
        sa.Column("profile_code", sa.String(length=8), nullable=True),
        sa.Column("central_value", sa.Double(), nullable=False),
        sa.Column("central_semantics", sa.String(length=32), nullable=False),
        sa.Column("raw_p10", sa.Double(), nullable=True),
        sa.Column("raw_p50", sa.Double(), nullable=True),
        sa.Column("raw_p90", sa.Double(), nullable=True),
        sa.Column("calibrated_lower", sa.Double(), nullable=True),
        sa.Column("calibrated_upper", sa.Double(), nullable=True),
        sa.Column("calibration_nominal_coverage", sa.Double(), nullable=True),
        sa.Column("calibration_status", sa.String(length=32), nullable=False),
        sa.Column("calibration_support_class", sa.String(length=64), nullable=True),
        sa.Column("calibration_version", sa.String(length=128), nullable=True),
        sa.Column("prediction_source", sa.String(length=32), nullable=False),
        sa.Column("hierarchy_status", sa.String(length=64), nullable=False),
        sa.Column("support_status", sa.String(length=32), nullable=False),
        sa.Column("fallback_status", sa.String(length=32), nullable=False),
        sa.Column("uncertainty_status", sa.String(length=32), nullable=False),
        sa.Column("provenance_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["operational_intelligence_snapshot.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "series_id",
            "target",
            "origin",
            "target_date",
            name="uq_operational_forecast_point",
        ),
    )
    op.create_index("ix_operational_forecast_snapshot_id", "operational_forecast", ["snapshot_id"], unique=False)
    op.create_index(
        "ix_operational_forecast_scope",
        "operational_forecast",
        [
            "snapshot_id",
            "origin",
            "level",
            "region_code",
            "org_code",
            "profile_code",
            "target",
            "target_date",
        ],
        unique=False,
    )
    op.create_table(
        "operational_signal",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("signal_type", sa.String(length=40), nullable=False),
        sa.Column("series_id", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.Date(), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=True),
        sa.Column("region_code", sa.String(length=4), nullable=True),
        sa.Column("profile_code", sa.String(length=8), nullable=True),
        sa.Column("inbox_rank", sa.Integer(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("concise_reason", sa.Text(), nullable=False),
        sa.Column("materiality_status", sa.String(length=64), nullable=True),
        sa.Column("support_status", sa.String(length=32), nullable=False),
        sa.Column("fallback_status", sa.String(length=32), nullable=False),
        sa.Column("uncertainty_status", sa.String(length=32), nullable=False),
        sa.Column("pressure_basis", sa.String(length=64), nullable=True),
        sa.Column("threshold_value", sa.Double(), nullable=True),
        sa.Column("threshold_status", sa.String(length=32), nullable=True),
        sa.Column("forecast_value", sa.Double(), nullable=True),
        sa.Column("uncertainty_lower", sa.Double(), nullable=True),
        sa.Column("uncertainty_upper", sa.Double(), nullable=True),
        sa.Column("first_crossing_date", sa.Date(), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("observed_anomaly_status", sa.String(length=32), nullable=True),
        sa.Column("observed_anomaly_present", sa.Boolean(), nullable=False),
        sa.Column("data_freshness", sa.Date(), nullable=True),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["operational_intelligence_snapshot.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "signal_id", name="uq_operational_signal_snapshot_id"),
    )
    op.create_index("ix_operational_signal_snapshot_id", "operational_signal", ["snapshot_id"], unique=False)
    op.create_index(
        "ix_operational_signal_order",
        "operational_signal",
        ["snapshot_id", "origin", "inbox_rank", "signal_id"],
        unique=False,
    )
    op.create_index(
        "ix_operational_signal_scope",
        "operational_signal",
        ["snapshot_id", "region_code", "org_code", "profile_code", "target"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_operational_signal_scope", table_name="operational_signal")
    op.drop_index("ix_operational_signal_order", table_name="operational_signal")
    op.drop_index("ix_operational_signal_snapshot_id", table_name="operational_signal")
    op.drop_table("operational_signal")
    op.drop_index("ix_operational_forecast_scope", table_name="operational_forecast")
    op.drop_index("ix_operational_forecast_snapshot_id", table_name="operational_forecast")
    op.drop_table("operational_forecast")
    op.drop_index(
        "ux_operational_intelligence_snapshot_active",
        table_name="operational_intelligence_snapshot",
    )
    op.drop_index(
        "ix_operational_intelligence_snapshot_is_active",
        table_name="operational_intelligence_snapshot",
    )
    op.drop_table("operational_intelligence_snapshot")
