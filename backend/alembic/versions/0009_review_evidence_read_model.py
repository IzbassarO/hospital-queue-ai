"""review evidence publication read model (forecast stress tests, decision alternatives)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-23 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _snapshot_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["snapshot_id"], ["review_evidence_snapshot.id"], ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "review_evidence_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("publication_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=32), nullable=False),
        sa.Column("publication_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("assurance_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("operational_publication_identity_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_code_commit", sa.String(length=40), nullable=False),
        sa.Column("current_origin", sa.Date(), nullable=False),
        sa.Column("freshness_state", sa.String(length=16), nullable=False),
        sa.Column("publication_status", sa.String(length=16), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("scenario_count", sa.Integer(), nullable=False),
        sa.Column("scenario_entity_count", sa.Integer(), nullable=False),
        sa.Column("scenario_cell_count", sa.Integer(), nullable=False),
        sa.Column("alternative_set_count", sa.Integer(), nullable=False),
        sa.Column("alternative_count", sa.Integer(), nullable=False),
        sa.Column("source_provenance", JSONB, nullable=False),
        sa.Column("limitations", JSONB, nullable=False),
        sa.Column("alternatives_summary", JSONB, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publication_id", name="uq_review_evidence_snapshot_publication_id"),
        sa.UniqueConstraint("publication_identity_sha256", name="uq_review_evidence_snapshot_identity"),
    )
    op.create_index("ix_review_evidence_snapshot_is_active", "review_evidence_snapshot", ["is_active"], unique=False)
    op.create_index(
        "ux_review_evidence_snapshot_active",
        "review_evidence_snapshot",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "review_scenario",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("scenario_id", sa.String(length=128), nullable=False),
        sa.Column("scenario_type", sa.String(length=32), nullable=False),
        sa.Column("classification", sa.String(length=48), nullable=False),
        sa.Column("lever_type", sa.String(length=64), nullable=False),
        sa.Column("multiplier", sa.Double(), nullable=True),
        sa.Column("scope_type", sa.String(length=64), nullable=False),
        sa.Column("horizon_start", sa.SmallInteger(), nullable=False),
        sa.Column("horizon_end", sa.SmallInteger(), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("uncertainty_method", sa.String(length=64), nullable=False),
        sa.Column("uncertainty_label", sa.String(length=64), nullable=False),
        sa.Column("coverage_guarantee", sa.Boolean(), nullable=False),
        sa.Column("causal_effect_claimed", sa.Boolean(), nullable=False),
        sa.Column("serving_claim", sa.Boolean(), nullable=False),
        sa.Column("baseline_reproduction", sa.String(length=16), nullable=True),
        sa.Column("details", JSONB, nullable=False),
        _snapshot_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "scenario_id", name="uq_review_scenario_snapshot_id"),
    )
    op.create_index("ix_review_scenario_snapshot_id", "review_scenario", ["snapshot_id"], unique=False)
    op.create_table(
        "review_scenario_entity",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("scenario_id", sa.String(length=128), nullable=False),
        sa.Column("series_id", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.Date(), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=False),
        sa.Column("region_code", sa.String(length=4), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("baseline_severity", sa.String(length=16), nullable=False),
        sa.Column("scenario_severity", sa.String(length=16), nullable=False),
        sa.Column("baseline_inbox_rank", sa.Integer(), nullable=True),
        sa.Column("scenario_inbox_rank", sa.Integer(), nullable=True),
        sa.Column("baseline_central", sa.Double(), nullable=False),
        sa.Column("scenario_central", sa.Double(), nullable=False),
        sa.Column("threshold_value", sa.Double(), nullable=True),
        sa.Column("absolute_delta", sa.Double(), nullable=False),
        sa.Column("relative_delta", sa.Double(), nullable=True),
        sa.Column("severity_changed", sa.Boolean(), nullable=False),
        sa.Column("entered_primary_inbox", sa.Boolean(), nullable=False),
        sa.Column("left_primary_inbox", sa.Boolean(), nullable=False),
        sa.Column("first_crossing_date", sa.Date(), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("materiality_status", sa.String(length=64), nullable=True),
        sa.Column("scenario_headline", sa.Text(), nullable=True),
        sa.Column("scenario_reason", sa.Text(), nullable=True),
        sa.Column("scenario_range_available", sa.Boolean(), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        _snapshot_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "scenario_id", "series_id", "target", "origin", name="uq_review_scenario_entity"
        ),
    )
    op.create_index("ix_review_scenario_entity_snapshot_id", "review_scenario_entity", ["snapshot_id"], unique=False)
    op.create_index(
        "ix_review_scenario_entity_signal", "review_scenario_entity", ["snapshot_id", "signal_id"], unique=False
    )
    op.create_table(
        "review_scenario_cell",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("scenario_id", sa.String(length=128), nullable=False),
        sa.Column("series_id", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.Date(), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("horizon", sa.SmallInteger(), nullable=False),
        sa.Column("baseline_central", sa.Double(), nullable=False),
        sa.Column("baseline_lower", sa.Double(), nullable=True),
        sa.Column("baseline_upper", sa.Double(), nullable=True),
        sa.Column("baseline_severity", sa.String(length=16), nullable=False),
        sa.Column("scenario_central", sa.Double(), nullable=False),
        sa.Column("scenario_lower", sa.Double(), nullable=True),
        sa.Column("scenario_upper", sa.Double(), nullable=True),
        sa.Column("scenario_severity", sa.String(length=16), nullable=False),
        sa.Column("threshold_value", sa.Double(), nullable=True),
        sa.Column("threshold_status", sa.String(length=32), nullable=True),
        sa.Column("scenario_uncertainty_status", sa.String(length=48), nullable=False),
        sa.Column("severity_changed", sa.Boolean(), nullable=False),
        sa.Column("source_reason_code", sa.String(length=96), nullable=True),
        _snapshot_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "scenario_id",
            "series_id",
            "target",
            "origin",
            "target_date",
            name="uq_review_scenario_cell",
        ),
    )
    op.create_index("ix_review_scenario_cell_snapshot_id", "review_scenario_cell", ["snapshot_id"], unique=False)
    op.create_index(
        "ix_review_scenario_cell_series",
        "review_scenario_cell",
        ["snapshot_id", "series_id", "target", "origin", "scenario_id"],
        unique=False,
    )
    op.create_table(
        "review_alternative_set",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("set_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_unit_id", sa.String(length=128), nullable=False),
        sa.Column("origin", sa.Date(), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("signal_id", sa.String(length=128), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("region_code", sa.String(length=4), nullable=False),
        sa.Column("series_id", sa.String(length=64), nullable=False),
        sa.Column("donor_severity", sa.String(length=16), nullable=False),
        sa.Column("priority_support_class", sa.String(length=64), nullable=False),
        sa.Column("materiality_status", sa.String(length=64), nullable=True),
        sa.Column("budget", sa.Double(), nullable=False),
        sa.Column("abstained", sa.Boolean(), nullable=False),
        sa.Column("abstention_codes", JSONB, nullable=False),
        sa.Column("receiver_candidates_considered", sa.Integer(), nullable=False),
        sa.Column("receiver_candidates_eligible", sa.Integer(), nullable=False),
        sa.Column("donor_minimum_transfer_fraction", sa.Double(), nullable=True),
        sa.Column("shortlist_bound", sa.Integer(), nullable=False),
        sa.Column("alternative_count", sa.Integer(), nullable=False),
        sa.Column("verification_failure_count", sa.Integer(), nullable=False),
        sa.Column("scientific_output_sha256", sa.String(length=64), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        _snapshot_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "set_id", name="uq_review_alternative_set_snapshot_id"),
    )
    op.create_index("ix_review_alternative_set_snapshot_id", "review_alternative_set", ["snapshot_id"], unique=False)
    op.create_index(
        "ix_review_alternative_set_signal", "review_alternative_set", ["snapshot_id", "signal_id"], unique=False
    )
    op.create_index(
        "ix_review_alternative_set_scope",
        "review_alternative_set",
        ["snapshot_id", "origin", "region_code", "org_code", "profile_code"],
        unique=False,
    )
    op.create_table(
        "review_alternative",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_id", sa.BigInteger(), nullable=False),
        sa.Column("set_id", sa.String(length=128), nullable=False),
        sa.Column("alternative_id", sa.String(length=128), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("donor_org_code", sa.String(length=8), nullable=False),
        sa.Column("receiver_org_code", sa.String(length=8), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("region_code", sa.String(length=4), nullable=False),
        sa.Column("transfer_fraction", sa.Double(), nullable=False),
        sa.Column("transferred_total", sa.Double(), nullable=False),
        sa.Column("donor_severity_before", sa.String(length=16), nullable=False),
        sa.Column("donor_severity_after", sa.String(length=16), nullable=False),
        sa.Column("receiver_severity_before", sa.String(length=16), nullable=False),
        sa.Column("receiver_severity_after", sa.String(length=16), nullable=False),
        sa.Column("verification_state", sa.String(length=32), nullable=False),
        sa.Column("forecast_support_tier", sa.String(length=32), nullable=False),
        sa.Column("receiver_range_evidence", sa.String(length=16), nullable=False),
        sa.Column("sensitivity_range_result", sa.String(length=48), nullable=False),
        sa.Column("feasibility_status", sa.String(length=48), nullable=False),
        sa.Column("receiver_no_worse_constraint_satisfied", sa.Boolean(), nullable=False),
        sa.Column("conservation_satisfied", sa.Boolean(), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        _snapshot_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "set_id", "alternative_id", name="uq_review_alternative_snapshot_id"),
    )
    op.create_index("ix_review_alternative_snapshot_id", "review_alternative", ["snapshot_id"], unique=False)
    op.create_index("ix_review_alternative_set", "review_alternative", ["snapshot_id", "set_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_review_alternative_set", table_name="review_alternative")
    op.drop_index("ix_review_alternative_snapshot_id", table_name="review_alternative")
    op.drop_table("review_alternative")
    op.drop_index("ix_review_alternative_set_scope", table_name="review_alternative_set")
    op.drop_index("ix_review_alternative_set_signal", table_name="review_alternative_set")
    op.drop_index("ix_review_alternative_set_snapshot_id", table_name="review_alternative_set")
    op.drop_table("review_alternative_set")
    op.drop_index("ix_review_scenario_cell_series", table_name="review_scenario_cell")
    op.drop_index("ix_review_scenario_cell_snapshot_id", table_name="review_scenario_cell")
    op.drop_table("review_scenario_cell")
    op.drop_index("ix_review_scenario_entity_signal", table_name="review_scenario_entity")
    op.drop_index("ix_review_scenario_entity_snapshot_id", table_name="review_scenario_entity")
    op.drop_table("review_scenario_entity")
    op.drop_index("ix_review_scenario_snapshot_id", table_name="review_scenario")
    op.drop_table("review_scenario")
    op.drop_index("ux_review_evidence_snapshot_active", table_name="review_evidence_snapshot")
    op.drop_index("ix_review_evidence_snapshot_is_active", table_name="review_evidence_snapshot")
    op.drop_table("review_evidence_snapshot")
