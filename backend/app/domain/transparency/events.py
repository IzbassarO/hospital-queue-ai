"""Ledger events of protocol v1: what each event states, built from plain source values.

The same builders serve three callers, which is what makes the ledger checkable against the database:
the live write path (app/services/transparency.py) and the server verifier, which rebuilds every covered payload from
the current source row and compares it with the ledger. The one-time backfill (migration 0019) carries its own frozen
copy of these builders, so a clean database is always migrated with protocol v1 exactly as released;
tests/test_transparency_migration.py fails when the two copies disagree on a byte.

Public payloads carry institution codes, dates, server-assigned ids, hashes and salted commitments. Every value a
client typed or chose freely — decision comment, actor, API-key label, idempotency key, the decision's subject id
(a signal or referral id), the simulation run id and the recommendation id — is never copied: only its commitment is
(docs/transparency-ledger.md §4).

A payload builder must stay byte-for-byte stable for v1: changing what an event states is a new event type or a
new protocol version, never an edit here.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.transparency.canonical import timestamp
from app.domain.transparency.chain import LedgerEntry, commitment, make_entry

PUBLISHED = "publication.published"
ACTIVATED = "publication.activated"
DEACTIVATED = "publication.deactivated"
DECISION_RECORDED = "decision.recorded"
# events that exist exactly once per subject (a unique index in the database enforces it)
ONCE_PER_SUBJECT = (PUBLISHED, DECISION_RECORDED)

# Every first-class publication kind, in the fixed order the backfill ranks them (dependencies first)
PUBLICATION_KINDS = (
    "model_assurance",
    "operational_intelligence",
    "review_evidence",
    "waiting_list",
    "referral_estimates",
    "verification_worklist",
)
SPECIALIST_DECISION = "specialist_decision"
HOSPITAL_DECISION = "hospital_decision"
DECISION_KINDS = (HOSPITAL_DECISION, SPECIALIST_DECISION)

SPECIALIST_PRIVATE_FIELDS = ("actor", "api_key_label", "comment", "idempotency_key", "run_id", "subject_id")
HOSPITAL_PRIVATE_FIELDS = ("actor", "api_key_label", "comment", "idempotency_key", "recommendation_id")


@dataclass(frozen=True)
class Event:
    """An entry before it is chained: what is stated, about which subject, at which instant."""

    event_type: str
    subject: str
    payload: dict[str, Any]
    created_at: str


def publication_subject(kind: str, publication_id: str) -> str:
    return f"publication:{kind}:{publication_id}"


def decision_subject(kind: str, decision_id: int) -> str:
    return f"{kind}:{decision_id}"


def _date(value: dt.date | None) -> str | None:
    return None if value is None else value.isoformat()


def commitments(salt: str, subject: str, row: Mapping[str, Any], fields: Iterable[str]) -> dict[str, str]:
    return {field: commitment(salt, subject, field, row.get(field)) for field in fields}


# ------------------------------------------------------------------------------------------------ publications
def published(kind: str, row: Mapping[str, Any]) -> Event:
    """A publication snapshot was inserted. ``row`` holds the snapshot columns (model assurance: assurance_id and
    assurance_identity_sha256 under the generic names publication_id / identity_sha256)."""
    if kind not in PUBLICATION_KINDS:
        raise ValueError(f"unknown publication kind {kind!r}")
    return Event(
        PUBLISHED,
        publication_subject(kind, row["publication_id"]),
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
        timestamp(row["published_at"]),
    )


def activation(event_type: str, kind: str, row: Mapping[str, Any], at: dt.datetime) -> Event:
    """A publication became (or stopped being) the active one. Written only at the moment it happens: the database
    keeps no history of activations, so these are never backfilled."""
    if event_type not in (ACTIVATED, DEACTIVATED):
        raise ValueError(event_type)
    return Event(
        event_type,
        publication_subject(kind, row["publication_id"]),
        {
            "identity_sha256": row["identity_sha256"],
            "publication_id": row["publication_id"],
            "publication_kind": kind,
            "snapshot_id": row["id"],
        },
        timestamp(at),
    )


# ------------------------------------------------------------------------------------------------ decisions
def specialist_decision(row: Mapping[str, Any], salt: str, publication_ledger_seq: int | None) -> Event:
    """A control-centre decision, linked to the operational publication that was active when it was written and to
    that publication's own ledger entry (None when the decision predates any published entry)."""
    subject = decision_subject(SPECIALIST_DECISION, row["id"])
    return Event(
        DECISION_RECORDED,
        subject,
        {
            "action": row["action"],
            "commitments": commitments(salt, subject, row, SPECIALIST_PRIVATE_FIELDS),
            "decision_id": row["id"],
            "decision_kind": SPECIALIST_DECISION,
            "evidence": {
                "operational_publication_identity_sha256": row["publication_identity_sha256"],
                "operational_publication_ledger_seq": publication_ledger_seq,
            },
            "org_code": row["org_code"],
            "origin": _date(row["origin"]),
            "profile_code": row["profile_code"],
            "region_code": row["region_code"],
            "sim_day": row["sim_day"],
            "subject_kind": row["subject_kind"],
        },
        timestamp(row["created_at"]),
    )


def hospital_decision(row: Mapping[str, Any], salt: str) -> Event:
    """A decision on a hospital × profile (decision_log, POST /decisions)."""
    subject = decision_subject(HOSPITAL_DECISION, row["id"])
    return Event(
        DECISION_RECORDED,
        subject,
        {
            "action": row["action"],
            "alternative_org_code": row["alternative_org_code"],
            "commitments": commitments(salt, subject, row, HOSPITAL_PRIVATE_FIELDS),
            "decision_id": row["id"],
            "decision_kind": HOSPITAL_DECISION,
            "org_code": row["org_code"],
            "profile_code": row["profile_code"],
            "region_code": row["region_code"],
        },
        timestamp(row["created_at"]),
    )


def chain_next(previous: LedgerEntry, event: Event) -> LedgerEntry:
    return make_entry(
        previous.seq + 1, event.created_at, event.event_type, event.subject, event.payload, previous.entry_hash
    )
