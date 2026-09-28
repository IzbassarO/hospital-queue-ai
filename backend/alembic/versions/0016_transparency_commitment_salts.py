"""private commitment salts for the transparency ledger

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-28 15:00:00

Stage one of the transparency ledger (docs/transparency-ledger.md §4, §5). The public ledger never copies free text
a person typed or that names a person; it carries a salted SHA-256 commitment instead, and the salt lives here,
separately, never exposed by an endpoint or an export.

Every decision that already exists gets its salt now, once, from the operating system's CSPRNG (`secrets`). The
ledger itself is built by the next migration (0017) from these stored salts, which is what makes that backfill
deterministic: downgrading only 0017 keeps this table, and upgrading again reproduces the same ledger bytes. Salts
are deliberately not derived from ids or timestamps: a predictable salt would let anyone test guesses of a comment
against its public commitment.

The table is append-only: a trigger rejects UPDATE and DELETE per row and TRUNCATE per statement (a row trigger
does not fire on TRUNCATE). The same trigger function guards the ledger in 0017.
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "transparency_commitment_salt"
REJECT_FUNCTION = """
CREATE FUNCTION transparency_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege',
              HINT = 'the transparency ledger and its commitment salts are never changed (docs/transparency-ledger.md)';
END;
$$
"""


def append_only(table: str) -> None:
    """UPDATE/DELETE rejected per row, TRUNCATE per statement."""
    op.execute(
        f"CREATE TRIGGER {table}_no_update_delete BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION transparency_reject_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION transparency_reject_mutation()"
    )


def grant_to_app_role(table: str) -> None:
    """The API's restricted login role (db/init.sql) may read and append, nothing else. No-op without that role."""
    op.execute(
        f"""
        DO $$
        DECLARE app_role text := current_setting('hqai.app_role', true);
        BEGIN
            IF app_role IS NOT NULL AND app_role <> '' THEN
                EXECUTE format('GRANT SELECT, INSERT ON TABLE {table} TO %I', app_role);
            END IF;
        END;
        $$
        """
    )


def upgrade() -> None:
    op.execute(REJECT_FUNCTION)
    op.create_table(
        TABLE,
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("salt", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("salt ~ '^[0-9a-f]{64}$'", name="ck_transparency_commitment_salt_hex"),
        sa.PrimaryKeyConstraint("subject"),
    )
    bind = op.get_bind()
    subjects = [f"hospital_decision:{row[0]}" for row in bind.execute(sa.text("SELECT id FROM decision_log"))]
    subjects += [f"specialist_decision:{row[0]}" for row in bind.execute(sa.text("SELECT id FROM specialist_decision"))]
    if subjects:
        bind.execute(
            sa.text(f"INSERT INTO {TABLE} (subject, salt) VALUES (:subject, :salt)"),
            [{"subject": subject, "salt": secrets.token_hex(32)} for subject in subjects],
        )
    append_only(TABLE)
    grant_to_app_role(TABLE)


def downgrade() -> None:
    op.drop_table(TABLE)
    op.execute("DROP FUNCTION transparency_reject_mutation()")
