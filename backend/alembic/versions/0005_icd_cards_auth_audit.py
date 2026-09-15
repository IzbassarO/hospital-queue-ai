"""ICD dictionary, model cards, decision idempotency, API keys and access log

- dim_icd: ICD-10 code -> name (filled by `make ingest`)
- model_registry.card: model card (title, intended use, limitations, display names), filled by `make predict`
  or `make registry`
- decision_log: alternative_org_code, idempotency_key (unique when set), api_key_label (who submitted)
- api_keys: hashed API keys with a role; access_log: one row per /api request

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-16 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dim_icd",
        sa.Column("icd10_code", sa.String(length=16), nullable=False),
        sa.Column("icd10_name", sa.Text(), nullable=False),
        sa.Column("name_share", sa.Double(), nullable=False),
        sa.Column("n_referrals", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("icd10_code"),
    )
    op.add_column("model_registry", sa.Column("card", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.add_column("decision_log", sa.Column("alternative_org_code", sa.String(length=8), nullable=True))
    op.add_column("decision_log", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("decision_log", sa.Column("api_key_label", sa.Text(), nullable=True))
    op.create_index(
        "ux_decision_log_idempotency_key",
        "decision_log",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('viewer', 'specialist', 'admin')", name="ck_api_keys_role"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ux_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "access_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("key_label", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("status", sa.SmallInteger(), nullable=False),
        sa.Column("latency_ms", sa.Double(), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("forwarded_for", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_access_log_ts", "access_log", ["ts"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_access_log_ts", table_name="access_log")
    op.drop_table("access_log")
    op.drop_index("ux_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index("ux_decision_log_idempotency_key", table_name="decision_log")
    op.drop_column("decision_log", "api_key_label")
    op.drop_column("decision_log", "idempotency_key")
    op.drop_column("decision_log", "alternative_org_code")
    op.drop_column("model_registry", "card")
    op.drop_table("dim_icd")
