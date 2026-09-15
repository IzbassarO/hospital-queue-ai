"""predictions and model registry

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-14 18:25:20.094991

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("trained_at", sa.DateTime(), nullable=False),
        sa.Column("train_window", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("registered_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("model_name", "version"),
    )
    op.create_index(op.f("ix_model_registry_is_current"), "model_registry", ["is_current"], unique=False)
    op.create_table(
        "pred_daily_forecast",
        sa.Column("series_id", sa.String(length=40), nullable=False),
        sa.Column("origin_date", sa.Date(), nullable=False),
        sa.Column("horizon", sa.SmallInteger(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=True),
        sa.Column("region_code", sa.String(length=4), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("pred_registrations", sa.Double(), nullable=False),
        sa.Column("pred_hospitalizations", sa.Double(), nullable=False),
        sa.Column("pred_queue", sa.Double(), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("series_id", "origin_date", "horizon"),
    )
    op.create_index(op.f("ix_pred_daily_forecast_org_code"), "pred_daily_forecast", ["org_code"], unique=False)
    op.create_index(op.f("ix_pred_daily_forecast_profile_code"), "pred_daily_forecast", ["profile_code"], unique=False)
    op.create_index(op.f("ix_pred_daily_forecast_region_code"), "pred_daily_forecast", ["region_code"], unique=False)
    op.create_index(op.f("ix_pred_daily_forecast_target_date"), "pred_daily_forecast", ["target_date"], unique=False)
    op.create_table(
        "pred_referral",
        sa.Column("referral_id", sa.BigInteger(), nullable=False),
        sa.Column("hospitalization_code", sa.String(length=32), nullable=False),
        sa.Column("registration_date", sa.Date(), nullable=False),
        sa.Column("org_code", sa.String(length=8), nullable=False),
        sa.Column("profile_code", sa.String(length=8), nullable=False),
        sa.Column("wait_model_version", sa.String(length=32), nullable=False),
        sa.Column("refusal_model_version", sa.String(length=32), nullable=False),
        sa.Column("pred_wait_days", sa.Double(), nullable=False),
        sa.Column("pred_refusal_prob", sa.Double(), nullable=False),
        sa.Column("explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("referral_id"),
    )
    op.create_index(
        op.f("ix_pred_referral_hospitalization_code"), "pred_referral", ["hospitalization_code"], unique=False
    )
    op.create_index(op.f("ix_pred_referral_org_code"), "pred_referral", ["org_code"], unique=False)
    op.create_index(op.f("ix_pred_referral_profile_code"), "pred_referral", ["profile_code"], unique=False)
    op.create_index(op.f("ix_pred_referral_registration_date"), "pred_referral", ["registration_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pred_referral_registration_date"), table_name="pred_referral")
    op.drop_index(op.f("ix_pred_referral_profile_code"), table_name="pred_referral")
    op.drop_index(op.f("ix_pred_referral_org_code"), table_name="pred_referral")
    op.drop_index(op.f("ix_pred_referral_hospitalization_code"), table_name="pred_referral")
    op.drop_table("pred_referral")
    op.drop_index(op.f("ix_pred_daily_forecast_target_date"), table_name="pred_daily_forecast")
    op.drop_index(op.f("ix_pred_daily_forecast_region_code"), table_name="pred_daily_forecast")
    op.drop_index(op.f("ix_pred_daily_forecast_profile_code"), table_name="pred_daily_forecast")
    op.drop_index(op.f("ix_pred_daily_forecast_org_code"), table_name="pred_daily_forecast")
    op.drop_table("pred_daily_forecast")
    op.drop_index(op.f("ix_model_registry_is_current"), table_name="model_registry")
    op.drop_table("model_registry")
