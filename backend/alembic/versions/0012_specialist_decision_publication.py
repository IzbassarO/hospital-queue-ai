"""specialist decisions carry the identity of the operational publication they answered

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-27 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("specialist_decision", sa.Column("publication_identity_sha256", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("specialist_decision", "publication_identity_sha256")
