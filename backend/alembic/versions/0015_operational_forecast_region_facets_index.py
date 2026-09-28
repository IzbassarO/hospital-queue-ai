"""index the operational forecast by region, for the overview and the region card

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-27 19:30:00

Without it, every /operational-intelligence/overview scanned the whole 305 MB forecast table to learn which 20
regions the publication covers (252 MB of buffers per request, a parallel sequential scan), and the region card
read 36 MB per facet. On a small shared server that exhausts the page cache and trips statement_timeout under
concurrency. The index covers `snapshot_id, region_code` for the overview and the card's count, and carries
`origin, target` so the card's two DISTINCT facets stay index-only as well.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_operational_forecast_region_facets"
TABLE = "operational_forecast"
COLUMNS = ["snapshot_id", "region_code", "origin", "target"]


def upgrade() -> None:
    # A plain CREATE INDEX: it runs inside the migration transaction and rolls back cleanly. It holds a SHARE lock
    # for the build (seconds on a table this size), which blocks a concurrent publish but never a read.
    op.create_index(INDEX, TABLE, COLUMNS, unique=False)


def downgrade() -> None:
    op.drop_index(INDEX, table_name=TABLE)
