"""model registry lineage

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-17 12:00:00

Historical rows remain valid with NULL lineage. New attributed rows are populated only after the
filesystem run/checkpoint/artifact evidence has been verified by the ML registry writer.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_registry", sa.Column("run_id", sa.String(length=128), nullable=True))
    op.add_column("model_registry", sa.Column("artifact_sha256", sa.String(length=64), nullable=True))
    op.add_column("model_registry", sa.Column("dataset_identity", sa.String(length=64), nullable=True))
    op.add_column("model_registry", sa.Column("config_identity", sa.String(length=64), nullable=True))
    op.add_column("model_registry", sa.Column("code_identity", sa.String(length=64), nullable=True))
    op.add_column("model_registry", sa.Column("evaluation_status", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("model_registry", "evaluation_status")
    op.drop_column("model_registry", "code_identity")
    op.drop_column("model_registry", "config_identity")
    op.drop_column("model_registry", "dataset_identity")
    op.drop_column("model_registry", "artifact_sha256")
    op.drop_column("model_registry", "run_id")
