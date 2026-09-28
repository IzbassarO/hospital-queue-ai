"""private commitment salts for the transparency ledger

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-28 15:00:00

Stage one of the transparency ledger (docs/transparency-ledger.md §4, §5). The public ledger never copies free text
or client-supplied identifiers; it carries a salted SHA-256 commitment instead, and the salt lives here,
separately, never exposed by an endpoint or an export.

Every decision that already exists gets its salt now, once, from the operating system's CSPRNG (`secrets`). The
ledger itself is built by the next migration (0019) from these stored salts, which is what makes that backfill
deterministic: downgrading only 0019 keeps this table, and upgrading again reproduces the same ledger bytes. Salts
are deliberately not derived from ids or timestamps: a predictable salt would let anyone test guesses of a comment
against its public commitment.

The table is append-only: a trigger rejects UPDATE and DELETE per row and TRUNCATE per statement (a row trigger
does not fire on TRUNCATE). The same trigger function guards the ledger in 0019.

Downgrade is audit-preserving (docs/transparency-ledger.md §10): the salts are random, so once dropped every
commitment made with them can never be checked again. Downgrade therefore refuses while the table holds a salt,
unless the operator passes the explicit `alembic -x transparency_audit=discard downgrade ...` after taking and
verifying a backup. No deployment tool passes that argument. The migration imports nothing from app/.
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0018"
down_revision: str | None = "0017"
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


AUDIT_REFUSAL = """refusing to downgrade {revision}: {what}.
The transparency ledger and its commitment salts are audit evidence, and a downgrade would destroy it
(docs/transparency-ledger.md §10). Nothing was changed. Instead:
  1. keep this schema: roll forward with a fix, or roll back application code that knows this revision;
  2. to return to an older schema anyway, first archive the evidence: GET /api/v1/transparency/export and the head
     (GET /api/v1/transparency/head) to a file outside the server, plus a fresh backup (make backup);
  3. then either restore a verified backup taken before the upgrade (make restore FILE=...), knowing that every
     ledger entry and salt written since then survives only in the archive, or rerun the downgrade with the
     explicit `alembic -x transparency_audit=discard downgrade <revision>`."""


def discard_confirmed() -> bool:
    """The operator's explicit consent to destroy audit evidence: an Alembic -x argument, never an environment
    default, so no deploy script or DEPLOY_ALLOW_* switch can pass it on the operator's behalf."""
    return context.get_x_argument(as_dictionary=True).get("transparency_audit") == "discard"


def downgrade() -> None:
    salts = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    if salts and not discard_confirmed():
        raise RuntimeError(AUDIT_REFUSAL.format(revision=revision, what=f"{TABLE} holds {salts} private salt(s)"))
    op.drop_table(TABLE)
    op.execute("DROP FUNCTION transparency_reject_mutation()")
