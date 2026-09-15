"""serving marts and decision log

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15 08:54:21.206480

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("region_code", sa.String(length=4), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("recommendation_id", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.CheckConstraint("action IN ('confirm', 'reject', 'defer')", name="ck_decision_log_action"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_decision_log_created_at"), "decision_log", ["created_at"], unique=False)
    op.create_index("ix_decision_log_org_profile", "decision_log", ["org_code", "profile_code"], unique=False)
    op.create_table(
        "mart_area_status",
        sa.Column("area_code", sa.String(length=4), nullable=False),
        sa.Column("area_level", sa.String(length=16), nullable=False),
        sa.Column("area_name", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("queue_now", sa.Integer(), nullable=False),
        sa.Column("registrations_28d", sa.Integer(), nullable=False),
        sa.Column("hospitalizations_28d", sa.Integer(), nullable=False),
        sa.Column("refusals_28d", sa.Integer(), nullable=False),
        sa.Column("refusal_rate_28d", sa.Double(), nullable=True),
        sa.Column("n_waits_28d", sa.Integer(), nullable=False),
        sa.Column("median_wait_28d", sa.Double(), nullable=True),
        sa.Column("forecast_registrations_14d", sa.Double(), nullable=True),
        sa.Column("forecast_hospitalizations_14d", sa.Double(), nullable=True),
        sa.Column("high_risk_share", sa.Double(), nullable=True),
        sa.Column("n_hospitals", sa.Integer(), nullable=False),
        sa.Column("n_hospital_profiles", sa.Integer(), nullable=False),
        sa.Column("n_hospital_profiles_ranked", sa.Integer(), nullable=False),
        sa.Column("load_index_max", sa.Double(), nullable=True),
        sa.Column("n_hospitals_high_load", sa.Integer(), nullable=False),
        sa.Column("n_hospital_profiles_high_load", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("area_code"),
    )
    op.create_table(
        "mart_build_info",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("built_at", sa.DateTime(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("row_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "mart_hospital_profile_status",
        sa.Column("org_code", sa.String(length=8), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("region_code", sa.String(length=4), nullable=False),
        sa.Column("region_name", sa.Text(), nullable=False),
        sa.Column("org_name", sa.Text(), nullable=False),
        sa.Column("profile_name", sa.Text(), nullable=False),
        sa.Column("forecast_method", sa.String(length=32), nullable=True),
        sa.Column("region_rank", sa.Integer(), nullable=True),
        sa.Column("region_n_ranked", sa.Integer(), nullable=False),
        sa.Column("in_region_top", sa.Boolean(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("queue_now", sa.Integer(), nullable=False),
        sa.Column("registrations_28d", sa.Integer(), nullable=False),
        sa.Column("hospitalizations_28d", sa.Integer(), nullable=False),
        sa.Column("refusals_28d", sa.Integer(), nullable=False),
        sa.Column("refusal_rate_28d", sa.Double(), nullable=True),
        sa.Column("n_waits_28d", sa.Integer(), nullable=False),
        sa.Column("median_wait_28d", sa.Double(), nullable=True),
        sa.Column("daily_throughput_28d", sa.Double(), nullable=False),
        sa.Column("backlog_days", sa.Double(), nullable=True),
        sa.Column("forecast_registrations_14d", sa.Double(), nullable=True),
        sa.Column("forecast_hospitalizations_14d", sa.Double(), nullable=True),
        sa.Column("n_test_referrals", sa.Integer(), nullable=False),
        sa.Column("high_risk_share", sa.Double(), nullable=True),
        sa.Column("queue_trend_4w", sa.Double(), nullable=True),
        sa.Column("has_sufficient_data", sa.Boolean(), nullable=False),
        sa.Column("backlog_score", sa.Double(), nullable=True),
        sa.Column("refusal_score", sa.Double(), nullable=True),
        sa.Column("trend_score", sa.Double(), nullable=True),
        sa.Column("load_index", sa.Double(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.PrimaryKeyConstraint("org_code", "profile_code"),
    )
    op.create_index(
        "ix_mart_hps_region_profile", "mart_hospital_profile_status", ["region_code", "profile_code"], unique=False
    )
    op.create_table(
        "mart_region_profile_status",
        sa.Column("region_code", sa.String(length=4), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("region_name", sa.Text(), nullable=False),
        sa.Column("profile_name", sa.Text(), nullable=False),
        sa.Column("n_hospitals", sa.Integer(), nullable=False),
        sa.Column("n_hospitals_high_load", sa.Integer(), nullable=False),
        sa.Column("load_index_max_hospital", sa.Double(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("queue_now", sa.Integer(), nullable=False),
        sa.Column("registrations_28d", sa.Integer(), nullable=False),
        sa.Column("hospitalizations_28d", sa.Integer(), nullable=False),
        sa.Column("refusals_28d", sa.Integer(), nullable=False),
        sa.Column("refusal_rate_28d", sa.Double(), nullable=True),
        sa.Column("n_waits_28d", sa.Integer(), nullable=False),
        sa.Column("median_wait_28d", sa.Double(), nullable=True),
        sa.Column("daily_throughput_28d", sa.Double(), nullable=False),
        sa.Column("backlog_days", sa.Double(), nullable=True),
        sa.Column("forecast_registrations_14d", sa.Double(), nullable=True),
        sa.Column("forecast_hospitalizations_14d", sa.Double(), nullable=True),
        sa.Column("n_test_referrals", sa.Integer(), nullable=False),
        sa.Column("high_risk_share", sa.Double(), nullable=True),
        sa.Column("queue_trend_4w", sa.Double(), nullable=True),
        sa.Column("has_sufficient_data", sa.Boolean(), nullable=False),
        sa.Column("backlog_score", sa.Double(), nullable=True),
        sa.Column("refusal_score", sa.Double(), nullable=True),
        sa.Column("trend_score", sa.Double(), nullable=True),
        sa.Column("load_index", sa.Double(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.PrimaryKeyConstraint("region_code", "profile_code"),
    )
    op.create_index("ix_pred_referral_org_profile", "pred_referral", ["org_code", "profile_code"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pred_referral_org_profile", table_name="pred_referral")
    op.drop_table("mart_region_profile_status")
    op.drop_index("ix_mart_hps_region_profile", table_name="mart_hospital_profile_status")
    op.drop_table("mart_hospital_profile_status")
    op.drop_table("mart_build_info")
    op.drop_table("mart_area_status")
    op.drop_index("ix_decision_log_org_profile", table_name="decision_log")
    op.drop_index(op.f("ix_decision_log_created_at"), table_name="decision_log")
    op.drop_table("decision_log")
