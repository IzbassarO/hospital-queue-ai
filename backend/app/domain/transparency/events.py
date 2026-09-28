"""Ledger events of protocol v1: what each event states, built from plain source values.

The same builders serve three callers, which is what makes the ledger checkable against the database:
the live write path (app/services/transparency.py), the one-time backfill (migration 0017) and the server verifier,
which rebuilds every covered payload from the current source row and compares it with the ledger.

Public payloads carry identifiers, codes, dates, hashes and salted commitments. Free text a person typed or that
names a person (decision comment, actor, API-key label, client idempotency key) is never copied: only its
commitment is (docs/transparency-ledger.md §4).

A payload builder must stay byte-for-byte stable for v1: changing what an event states is a new event type or a
new protocol version, never an edit here.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.transparency.canonical import timestamp
from app.domain.transparency.chain import LedgerEntry, commitment, genesis, make_entry

PUBLISHED = "publication.published"
ACTIVATED = "publication.activated"
DEACTIVATED = "publication.deactivated"
DECISION_RECORDED = "decision.recorded"
# events that exist exactly once per subject (a unique index in the database enforces it)
ONCE_PER_SUBJECT = (PUBLISHED, DECISION_RECORDED)

# Publication kinds in their fixed backfill order (dependencies first: assurance, then what verifies against it)
PUBLICATION_KINDS = ("model_assurance", "operational_intelligence", "review_evidence", "waiting_list")
SPECIALIST_DECISION = "specialist_decision"
HOSPITAL_DECISION = "hospital_decision"
DECISION_KINDS = (HOSPITAL_DECISION, SPECIALIST_DECISION)
# one global order across source kinds for the backfill: (event time, this rank, durable id)
SOURCE_RANK = {
    **{kind: i for i, kind in enumerate(PUBLICATION_KINDS, start=1)},
    HOSPITAL_DECISION: 5,
    SPECIALIST_DECISION: 6,
}

SPECIALIST_PRIVATE_FIELDS = ("actor", "api_key_label", "comment", "idempotency_key")
HOSPITAL_PRIVATE_FIELDS = ("actor", "api_key_label", "comment", "idempotency_key")


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
            "run_id": row["run_id"],
            "sim_day": row["sim_day"],
            "subject_id": row["subject_id"],
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
            "recommendation_id": row["recommendation_id"],
            "region_code": row["region_code"],
        },
        timestamp(row["created_at"]),
    )


def operational_seq_by_identity(entries: Iterable[LedgerEntry]) -> dict[str, int]:
    """identity → seq of its publication.published entry, for the evidence link of later decisions."""
    found: dict[str, int] = {}
    for entry in entries:
        if (
            entry.event_type == PUBLISHED
            and entry.payload.get("publication_kind") == "operational_intelligence"
            and entry.payload.get("identity_sha256") not in found
        ):
            found[entry.payload["identity_sha256"]] = entry.seq
    return found


# ------------------------------------------------------------------------------------------------ backfill
@dataclass(frozen=True)
class BackfillSource:
    """Durable rows as plain mappings. ``salts`` maps a decision subject to its private salt."""

    publications: Mapping[str, list[Mapping[str, Any]]]
    hospital_decisions: list[Mapping[str, Any]]
    specialist_decisions: list[Mapping[str, Any]]
    salts: Mapping[str, str]


def backfill(source: BackfillSource) -> list[LedgerEntry]:
    """The deterministic ledger of what the durable rows prove: genesis, then one entry per publication snapshot
    (publication.published at published_at) and per decision (decision.recorded at created_at), in the single
    global order (event time, SOURCE_RANK, id). Nothing else is stated: activations and deactivations are not
    stored with a time, so none are invented. Same rows and salts in, same bytes out."""
    planned: list[tuple[dt.datetime, int, int, str, Mapping[str, Any]]] = []
    for kind in PUBLICATION_KINDS:
        for row in source.publications.get(kind, []):
            planned.append((row["published_at"], SOURCE_RANK[kind], row["id"], kind, row))
    for row in source.hospital_decisions:
        planned.append((row["created_at"], SOURCE_RANK[HOSPITAL_DECISION], row["id"], HOSPITAL_DECISION, row))
    for row in source.specialist_decisions:
        planned.append((row["created_at"], SOURCE_RANK[SPECIALIST_DECISION], row["id"], SPECIALIST_DECISION, row))
    for when, *_ in planned:
        if when.tzinfo is None:
            raise ValueError("source timestamps must be time-zone aware")
    planned.sort(key=lambda item: (item[0].astimezone(dt.UTC), item[1], item[2]))

    chain = [genesis()]
    operational_seq: dict[str, int] = {}
    for _when, _rank, _id, kind, row in planned:
        if kind in PUBLICATION_KINDS:
            event = published(kind, row)
        else:
            subject = decision_subject(kind, row["id"])
            salt = source.salts.get(subject)
            if salt is None:
                raise ValueError(f"{subject} has no commitment salt: run migration 0016 first")
            if kind == SPECIALIST_DECISION:
                identity = row["publication_identity_sha256"]
                event = specialist_decision(row, salt, operational_seq.get(identity) if identity else None)
            else:
                event = hospital_decision(row, salt)
        entry = chain_next(chain[-1], event)
        chain.append(entry)
        if event.event_type == PUBLISHED and kind == "operational_intelligence":
            operational_seq.setdefault(event.payload["identity_sha256"], entry.seq)
    return chain


def chain_next(previous: LedgerEntry, event: Event) -> LedgerEntry:
    return make_entry(
        previous.seq + 1, event.created_at, event.event_type, event.subject, event.payload, previous.entry_hash
    )
