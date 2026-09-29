"""transparency ledger: append-only hash chain with a deterministic backfill

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-28 15:10:00

Stage two of the transparency ledger (docs/transparency-ledger.md). Creates `transparency_ledger`, fills it with what
the durable rows truthfully prove, and makes it append-only.

Backfill. Entry 1 is the protocol v1 genesis, whose timestamp is a protocol constant, not the migration's clock.
Then one `publication.published` per publication snapshot (at its published_at) and one `decision.recorded` per
decision (at its created_at), in one global order: (event time, source rank, id) with the ranks model assurance 1,
operational intelligence 2, review evidence 3, waiting list 4, referral estimates 5, verification worklist 6,
hospital decision 7, specialist decision 8. Nothing else is stated: the database keeps no history of which
publication was active when, so no activation or deactivation is backfilled — those are only written live, at the
moment they happen. Private fields are committed with the salts 0018 stored, so the same rows give the same bytes
every time this migration runs.

Replay safety. Everything the backfill hashes is FROZEN in this file: canonical JSON, the genesis, the commitment
scheme, the payload builders and the global order are a copy of protocol v1, not an import of app/. A migration runs
again on every clean database for as long as the project lives; if it imported the application's builders, a later
edit of those would silently change what this historical migration writes. The application keeps its own copy for
the live path and the server verifier, and backend/tests/test_transparency_migration.py fails the moment the two
copies disagree on a single byte (docs/transparency-ledger.md §9).

Guarantees. UPDATE and DELETE are rejected per row and TRUNCATE per statement by triggers; seq is the primary key,
entry_hash and prev_hash are unique (a second child of one entry — a fork — cannot be inserted), and a decision can
be recorded once. The API role may SELECT and INSERT only.

Downgrade is audit-preserving (docs/transparency-ledger.md §10). It drops the ledger only when the ledger is exactly
what upgrading again would rebuild — genesis plus the backfill of the current rows, byte for byte — so nothing is
lost. Once the ledger holds anything written live (activations, deactivations, the commit order of concurrent
appends, a publication or decision the backfill would place differently) the downgrade refuses with the recovery
procedure, unless the operator passes the explicit `alembic -x transparency_audit=discard downgrade ...`.
"""

import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
# tools/deploy.sh rollback never downgrades across this revision (docs/deploy-shared-server.md §10).
AUDIT_SENSITIVE = True

TABLE = "transparency_ledger"

# ================================================================================================ frozen protocol v1
# Do not edit to follow app/domain/transparency: this is what the migration wrote on the day it was released.
ZERO_HASH = "0" * 64
GENESIS_CREATED_AT = "2026-09-28T00:00:00.000000Z"
GENESIS_PAYLOAD = {
    "canonicalization": "hqai-canonical-json-v1",
    "commitment_scheme": "sha256-salted-v1",
    "hash_algorithm": "sha256",
    "protocol": "aqyl-kezek-transparency-ledger",
    "protocol_version": 1,
}
PUBLICATION_TABLES = {
    "model_assurance": "model_assurance_snapshot",
    "operational_intelligence": "operational_intelligence_snapshot",
    "review_evidence": "review_evidence_snapshot",
    "waiting_list": "waiting_list_snapshot",
    "referral_estimates": "referral_estimate_snapshot",
    "verification_worklist": "verification_worklist_snapshot",
}
SOURCE_RANK = {
    **{kind: rank for rank, kind in enumerate(PUBLICATION_TABLES, start=1)},
    "hospital_decision": 7,
    "specialist_decision": 8,
}
SPECIALIST_PRIVATE = ("actor", "api_key_label", "comment", "idempotency_key", "run_id", "subject_id")
HOSPITAL_PRIVATE = ("actor", "api_key_label", "comment", "idempotency_key", "recommendation_id")
_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _string(value: str) -> str:
    if "\x00" in value:
        raise ValueError("U+0000 is not allowed in canonical strings")
    value.encode("utf-8")  # lone surrogates raise
    return '"' + "".join(_ESCAPES.get(c) or (f"\\u{ord(c):04x}" if c < " " else c) for c in value) + '"'


def canonical(value: Any) -> str:
    """hqai-canonical-json-v1 for the values a backfill payload holds (null, booleans, safe integers, strings,
    arrays, objects with sorted [a-z][a-z0-9_]* keys, no whitespace)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > 2**53 - 1:
            raise ValueError(f"{value} is outside the safe integer range")
        return str(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(_string(key) + ":" + canonical(value[key]) for key in sorted(value)) + "}"
    raise ValueError(f"{type(value).__name__} is not a canonical JSON value")


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def timestamp(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("source timestamps must be time-zone aware")
    utc = value.astimezone(dt.UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond:06d}Z"


def commitment(salt: str, subject: str, field: str, value: str | None) -> str:
    return _sha256({"field": field, "salt": salt, "scheme": "sha256-salted-v1", "subject": subject, "value": value})


def entry(seq: int, created_at: str, event_type: str, subject: str, payload: dict, prev_hash: str) -> dict:
    material = {
        "created_at": created_at,
        "event_type": event_type,
        "payload": payload,
        "prev_hash": prev_hash,
        "seq": seq,
        "subject": subject,
    }
    return {**material, "entry_hash": _sha256(material)}


def genesis() -> dict:
    return entry(1, GENESIS_CREATED_AT, "ledger.genesis", "ledger:aqyl-kezek", dict(GENESIS_PAYLOAD), ZERO_HASH)


def published(kind: str, row: dict) -> tuple[str, str, dict]:
    return (
        timestamp(row["published_at"]),
        f"publication:{kind}:{row['publication_id']}",
        {
            "bundle_sha256": row["bundle_sha256"],
            "contract_version": row["contract_version"],
            "identity_sha256": row["identity_sha256"],
            "publication_id": row["publication_id"],
            "publication_kind": kind,
            "published_at": timestamp(row["published_at"]),
            "schema_version": row["schema_version"],
            "snapshot_id": row["id"],
            "source_code_commit": row["source_code_commit"],
        },
    )


def specialist_decision(row: dict, salt: str, publication_seq: int | None) -> tuple[str, str, dict]:
    subject = f"specialist_decision:{row['id']}"
    return (
        timestamp(row["created_at"]),
        subject,
        {
            "action": row["action"],
            "commitments": {f: commitment(salt, subject, f, row[f]) for f in SPECIALIST_PRIVATE},
            "decision_id": row["id"],
            "decision_kind": "specialist_decision",
            "evidence": {
                "operational_publication_identity_sha256": row["publication_identity_sha256"],
                "operational_publication_ledger_seq": publication_seq,
            },
            "org_code": row["org_code"],
            "origin": None if row["origin"] is None else row["origin"].isoformat(),
            "profile_code": row["profile_code"],
            "region_code": row["region_code"],
            "sim_day": row["sim_day"],
            "subject_kind": row["subject_kind"],
        },
    )


def hospital_decision(row: dict, salt: str) -> tuple[str, str, dict]:
    subject = f"hospital_decision:{row['id']}"
    return (
        timestamp(row["created_at"]),
        subject,
        {
            "action": row["action"],
            "alternative_org_code": row["alternative_org_code"],
            "commitments": {f: commitment(salt, subject, f, row[f]) for f in HOSPITAL_PRIVATE},
            "decision_id": row["id"],
            "decision_kind": "hospital_decision",
            "org_code": row["org_code"],
            "profile_code": row["profile_code"],
            "region_code": row["region_code"],
        },
    )


def backfill(
    publications: dict[str, list[dict]], hospital: list[dict], specialist: list[dict], salts: dict[str, str]
) -> list[dict]:
    """Genesis, then one entry per snapshot and per decision in the order (event time, SOURCE_RANK, id)."""
    planned = [
        (row["published_at"], SOURCE_RANK[kind], row["id"], kind, row)
        for kind in PUBLICATION_TABLES
        for row in publications.get(kind, [])
    ]
    planned += [
        (row["created_at"], SOURCE_RANK["hospital_decision"], row["id"], "hospital_decision", row) for row in hospital
    ]
    planned += [
        (row["created_at"], SOURCE_RANK["specialist_decision"], row["id"], "specialist_decision", row)
        for row in specialist
    ]
    for when, *_ in planned:
        if when.tzinfo is None:
            raise ValueError("source timestamps must be time-zone aware")
    planned.sort(key=lambda item: (item[0].astimezone(dt.UTC), item[1], item[2]))

    chain = [genesis()]
    operational_seq: dict[str, int] = {}
    for _when, _rank, _id, kind, row in planned:
        if kind in PUBLICATION_TABLES:
            created_at, subject, payload = published(kind, row)
            event_type = "publication.published"
        else:
            salt = salts.get(f"{kind}:{row['id']}")
            if salt is None:
                raise ValueError(f"{kind}:{row['id']} has no commitment salt: migration 0018 has not run")
            if kind == "specialist_decision":
                identity = row["publication_identity_sha256"]
                created_at, subject, payload = specialist_decision(
                    row, salt, operational_seq.get(identity) if identity else None
                )
            else:
                created_at, subject, payload = hospital_decision(row, salt)
            event_type = "decision.recorded"
        previous = chain[-1]
        chain.append(entry(previous["seq"] + 1, created_at, event_type, subject, payload, previous["entry_hash"]))
        if kind == "operational_intelligence":
            operational_seq.setdefault(payload["identity_sha256"], chain[-1]["seq"])
    return chain


# ================================================================================================ source rows
SPECIALIST_QUERY = """
    SELECT id, created_at, origin, run_id, sim_day, subject_kind, subject_id, region_code, org_code, profile_code,
           action, comment, actor, api_key_label, idempotency_key, publication_identity_sha256
    FROM specialist_decision"""
HOSPITAL_QUERY = """
    SELECT id, created_at, region_code, org_code, profile_code, recommendation_id, action, comment, actor,
           alternative_org_code, idempotency_key, api_key_label
    FROM decision_log"""


def _publication_query(kind: str) -> str:
    assurance = kind == "model_assurance"
    return f"""
        SELECT id, {"assurance_id" if assurance else "publication_id"} AS publication_id,
               {"assurance_identity_sha256" if assurance else "publication_identity_sha256"} AS identity_sha256,
               bundle_sha256, contract_version, schema_version, source_code_commit, published_at
        FROM {PUBLICATION_TABLES[kind]}"""


def _rows(bind, query: str) -> list[dict]:
    return [dict(row) for row in bind.execute(sa.text(query)).mappings()]


def backfill_from_database(bind) -> list[dict]:
    return backfill(
        {kind: _rows(bind, _publication_query(kind)) for kind in PUBLICATION_TABLES},
        _rows(bind, HOSPITAL_QUERY),
        _rows(bind, SPECIALIST_QUERY),
        {row["subject"]: row["salt"] for row in _rows(bind, "SELECT subject, salt FROM transparency_commitment_salt")},
    )


# ================================================================================================ migration
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
    bind.execute(
        sa.text(
            f"INSERT INTO {TABLE} (seq, created_at, event_type, subject, payload, prev_hash, entry_hash) "
            "VALUES (:seq, CAST(:created_at AS timestamptz), :event_type, :subject, CAST(:payload AS jsonb), "
            ":prev_hash, :entry_hash)"
        ),
        [{**e, "payload": json.dumps(e["payload"], ensure_ascii=False)} for e in backfill_from_database(bind)],
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
    bind = op.get_bind()
    stored = [tuple(row) for row in bind.execute(sa.text(f"SELECT seq, entry_hash FROM {TABLE} ORDER BY seq"))]
    try:
        rebuilt = [(e["seq"], e["entry_hash"]) for e in backfill_from_database(bind)]
    except ValueError:
        rebuilt = None
    if stored != rebuilt and not discard_confirmed():
        raise RuntimeError(
            AUDIT_REFUSAL.format(
                revision=revision,
                what=f"{TABLE} holds {len(stored)} entries that upgrading again would not rebuild byte for byte "
                "(entries written live)",
            )
        )
    op.drop_table(TABLE)
