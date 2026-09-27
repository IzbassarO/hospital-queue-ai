"""access log becomes usable as an audit trail: query string, request id and the indexes it is filtered by

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-27 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("access_log", sa.Column("query", sa.String(length=500), nullable=True))
    op.add_column("access_log", sa.Column("request_id", sa.String(length=128), nullable=True))
    op.create_index("ix_access_log_key_label_ts", "access_log", ["key_label", "ts"])
    op.create_index("ix_access_log_status_ts", "access_log", ["status", "ts"])


def downgrade() -> None:
    op.drop_index("ix_access_log_status_ts", table_name="access_log")
    op.drop_index("ix_access_log_key_label_ts", table_name="access_log")
    op.drop_column("access_log", "request_id")
    op.drop_column("access_log", "query")
