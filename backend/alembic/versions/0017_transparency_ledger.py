"""transparency ledger: append-only hash chain with a deterministic backfill

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-28 15:10:00

Stage two of the transparency ledger (docs/transparency-ledger.md). Creates `transparency_ledger`, fills it with what
the durable rows truthfully prove, and makes it append-only.

Backfill. Entry 1 is the protocol v1 genesis, whose timestamp is a protocol constant, not the migration's clock.
Then one `publication.published` per publication snapshot (at its published_at) and one `decision.recorded` per
decision (at its created_at), in one global order: (event time, source rank, id) with the ranks model assurance 1,
operational intelligence 2, review evidence 3, waiting list 4, hospital decision 5, specialist decision 6. Nothing
else is stated: the database keeps no history of which publication was active when, so no activation or
deactivation is backfilled — those are only written live, at the moment they happen. Private fields are committed
with the salts 0016 stored, so the same rows give the same bytes every time this migration runs.

Guarantees. UPDATE and DELETE are rejected per row and TRUNCATE per statement by triggers; seq is the primary key,
entry_hash and prev_hash are unique (a second child of one entry — a fork — cannot be inserted), and a decision can
be recorded once. The API role may SELECT and INSERT only. The payload builders and the canonical JSON are the
application's own (app/domain/transparency), shared with the live write path and the server verifier; they are
frozen for protocol v1.

Downgrade drops the ledger. Everything the backfill states is rebuilt byte-identically by upgrading again (the salts
stay in 0016); events that exist only because they were written live — activations, deactivations and the order of
concurrent appends — are lost with it.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.domain.transparency import events
from app.domain.transparency.canonical import parse_timestamp

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "transparency_ledger"
PUBLICATION_QUERIES = {
    "model_assurance": """
        SELECT id, assurance_id AS publication_id, assurance_identity_sha256 AS identity_sha256, bundle_sha256,
               contract_version, schema_version, source_code_commit, published_at
        FROM model_assurance_snapshot""",
    **{
        kind: f"""
        SELECT id, publication_id, publication_identity_sha256 AS identity_sha256, bundle_sha256,
               contract_version, schema_version, source_code_commit, published_at
        FROM {kind}_snapshot"""
        for kind in ("operational_intelligence", "review_evidence", "waiting_list")
    },
}
SPECIALIST_QUERY = """
    SELECT id, created_at, origin, run_id, sim_day, subject_kind, subject_id, region_code, org_code, profile_code,
           action, comment, actor, api_key_label, idempotency_key, publication_identity_sha256
    FROM specialist_decision"""
HOSPITAL_QUERY = """
    SELECT id, created_at, region_code, org_code, profile_code, recommendation_id, action, comment, actor,
           alternative_org_code, idempotency_key, api_key_label
    FROM decision_log"""


def _rows(bind, query: str) -> list[dict]:
    return [dict(row) for row in bind.execute(sa.text(query)).mappings()]


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("seq", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint("seq >= 1", name="ck_transparency_ledger_seq"),
        sa.CheckConstraint("prev_hash ~ '^[0-9a-f]{64}$'", name="ck_transparency_ledger_prev_hash"),
        sa.CheckConstraint("entry_hash ~ '^[0-9a-f]{64}$'", name="ck_transparency_ledger_entry_hash"),
        sa.PrimaryKeyConstraint("seq"),
        sa.UniqueConstraint("entry_hash", name="uq_transparency_ledger_entry_hash"),
        sa.UniqueConstraint("prev_hash", name="uq_transparency_ledger_prev_hash"),
    )
    op.create_index("ix_transparency_ledger_subject", TABLE, ["subject"], unique=False)
    op.create_index(
        "ux_transparency_ledger_decision_subject",
        TABLE,
        ["subject"],
        unique=True,
        postgresql_where=sa.text("event_type = 'decision.recorded'"),
    )

    bind = op.get_bind()
    source = events.BackfillSource(
        publications={kind: _rows(bind, query) for kind, query in PUBLICATION_QUERIES.items()},
        hospital_decisions=_rows(bind, HOSPITAL_QUERY),
        specialist_decisions=_rows(bind, SPECIALIST_QUERY),
        salts={
            row["subject"]: row["salt"] for row in _rows(bind, "SELECT subject, salt FROM transparency_commitment_salt")
        },
    )
    entries = events.backfill(source)
    bind.execute(
        sa.text(
            f"INSERT INTO {TABLE} (seq, created_at, event_type, subject, payload, prev_hash, entry_hash) "
            "VALUES (:seq, :created_at, :event_type, :subject, CAST(:payload AS jsonb), :prev_hash, :entry_hash)"
        ),
        [
            {
                "seq": entry.seq,
                "created_at": parse_timestamp(entry.created_at),
                "event_type": entry.event_type,
                "subject": entry.subject,
                "payload": json.dumps(entry.payload, ensure_ascii=False),
                "prev_hash": entry.prev_hash,
                "entry_hash": entry.entry_hash,
            }
            for entry in entries
        ],
    )

    op.execute(
        f"CREATE TRIGGER {TABLE}_no_update_delete BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION transparency_reject_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER {TABLE}_no_truncate BEFORE TRUNCATE ON {TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION transparency_reject_mutation()"
    )
    op.execute(
        f"""
        DO $$
        DECLARE app_role text := current_setting('hqai.app_role', true);
        BEGIN
            IF app_role IS NOT NULL AND app_role <> '' THEN
                EXECUTE format('GRANT SELECT, INSERT ON TABLE {TABLE} TO %I', app_role);
            END IF;
        END;
        $$
        """
    )


def downgrade() -> None:
    op.drop_table(TABLE)
