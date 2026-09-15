"""excess queue trend

queue_trend_raw_4w keeps the raw 4-week queue trend; queue_trend_4w now holds the excess trend
(raw minus the national median raw trend). Values appear after the next `make marts`.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15 13:43:45.763035

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mart_hospital_profile_status", sa.Column("queue_trend_raw_4w", sa.Double(), nullable=True))
    op.add_column("mart_region_profile_status", sa.Column("queue_trend_raw_4w", sa.Double(), nullable=True))


def downgrade() -> None:
    op.drop_column("mart_region_profile_status", "queue_trend_raw_4w")
    op.drop_column("mart_hospital_profile_status", "queue_trend_raw_4w")
