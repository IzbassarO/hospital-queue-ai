"""PostgreSQL access for the transparency ledger and its private commitment salts.

Appends are serialized by a transaction-scoped advisory lock (`pg_advisory_xact_lock`): the lock is taken inside the
caller's transaction and released only by its COMMIT or ROLLBACK, so the head read after taking it is the committed
head and no two transactions can chain onto the same predecessor. Nothing here commits. The unique constraints on
seq, prev_hash and entry_hash are the second line of defence: a writer that skipped the lock would fail, not fork.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DecisionLog,
    ModelAssuranceSnapshot,
    OperationalIntelligenceSnapshot,
    ReviewEvidenceSnapshot,
    SpecialistDecision,
    TransparencyCommitmentSalt,
    TransparencyLedger,
    WaitingListSnapshot,
)

# Key of the advisory lock that serializes appends: ASCII "hqaiTLv1" read as a signed 64-bit integer. Any other
# code taking advisory locks must not use this key.
LEDGER_LOCK_KEY = int.from_bytes(b"hqaiTLv1", "big", signed=True)

SNAPSHOT_MODELS = {
    "model_assurance": ModelAssuranceSnapshot,
    "operational_intelligence": OperationalIntelligenceSnapshot,
    "review_evidence": ReviewEvidenceSnapshot,
    "waiting_list": WaitingListSnapshot,
}


def lock_for_append(session: Session) -> None:
    session.execute(select(func.pg_advisory_xact_lock(LEDGER_LOCK_KEY)))


def head(session: Session) -> TransparencyLedger | None:
    return session.scalar(select(TransparencyLedger).order_by(TransparencyLedger.seq.desc()).limit(1))


def insert(session: Session, row: TransparencyLedger) -> None:
    session.add(row)
    session.flush()


def by_seq(session: Session, seq: int) -> TransparencyLedger | None:
    return session.get(TransparencyLedger, seq)


def page(
    session: Session, *, limit: int, offset: int, descending: bool, event_type: str | None
) -> tuple[list[TransparencyLedger], int]:
    where = [TransparencyLedger.event_type == event_type] if event_type else []
    total = session.scalar(select(func.count()).select_from(TransparencyLedger).where(*where)) or 0
    order = TransparencyLedger.seq.desc() if descending else TransparencyLedger.seq.asc()
    rows = session.scalars(select(TransparencyLedger).where(*where).order_by(order).limit(limit).offset(offset))
    return list(rows), total


def by_hash_prefix(session: Session, prefix: str, limit: int) -> list[TransparencyLedger]:
    query = select(TransparencyLedger).where(TransparencyLedger.entry_hash.startswith(prefix, autoescape=True))
    return list(session.scalars(query.order_by(TransparencyLedger.seq).limit(limit)))


def by_subject(session: Session, subject: str, limit: int) -> list[TransparencyLedger]:
    query = select(TransparencyLedger).where(TransparencyLedger.subject == subject)
    return list(session.scalars(query.order_by(TransparencyLedger.seq).limit(limit)))


def recorded_for(session: Session, subjects: Iterable[str], event_type: str) -> dict[str, TransparencyLedger]:
    """First entry of `event_type` per subject (decision.recorded is unique per subject by index)."""
    wanted = list(set(subjects))
    if not wanted:
        return {}
    rows = session.scalars(
        select(TransparencyLedger)
        .where(TransparencyLedger.subject.in_(wanted), TransparencyLedger.event_type == event_type)
        .order_by(TransparencyLedger.seq)
    )
    found: dict[str, TransparencyLedger] = {}
    for row in rows:
        found.setdefault(row.subject, row)
    return found


def iterate(session: Session, batch: int = 1000) -> Iterator[TransparencyLedger]:
    """Every entry in seq order, streamed in batches (verification and export)."""
    last = 0
    while True:
        rows = list(
            session.scalars(
                select(TransparencyLedger)
                .where(TransparencyLedger.seq > last)
                .order_by(TransparencyLedger.seq)
                .limit(batch)
            )
        )
        if not rows:
            return
        yield from rows
        last = rows[-1].seq


# ------------------------------------------------------------------------------------------------ salts
def insert_salt(session: Session, subject: str, salt: str) -> None:
    session.add(TransparencyCommitmentSalt(subject=subject, salt=salt))
    session.flush()


def salt(session: Session, subject: str) -> str | None:
    return session.scalar(select(TransparencyCommitmentSalt.salt).where(TransparencyCommitmentSalt.subject == subject))


def all_salts(session: Session) -> dict[str, str]:
    return dict(session.execute(select(TransparencyCommitmentSalt.subject, TransparencyCommitmentSalt.salt)).all())


# ------------------------------------------------------------------------------------------------ covered sources
def _mappings(session: Session, model, columns: Iterable[str]) -> list[dict[str, Any]]:
    selected = [getattr(model, name).label(name) for name in columns]
    return [dict(row) for row in session.execute(select(*selected)).mappings()]


SPECIALIST_COLUMNS = (
    "id",
    "created_at",
    "origin",
    "run_id",
    "sim_day",
    "subject_kind",
    "subject_id",
    "region_code",
    "org_code",
    "profile_code",
    "action",
    "comment",
    "actor",
    "api_key_label",
    "idempotency_key",
    "publication_identity_sha256",
)
HOSPITAL_COLUMNS = (
    "id",
    "created_at",
    "region_code",
    "org_code",
    "profile_code",
    "recommendation_id",
    "action",
    "comment",
    "actor",
    "alternative_org_code",
    "idempotency_key",
    "api_key_label",
)


def specialist_decisions(session: Session) -> list[dict[str, Any]]:
    return _mappings(session, SpecialistDecision, SPECIALIST_COLUMNS)


def hospital_decisions(session: Session) -> list[dict[str, Any]]:
    return _mappings(session, DecisionLog, HOSPITAL_COLUMNS)


def publications(session: Session) -> dict[str, list[dict[str, Any]]]:
    """Every snapshot of every publication kind under the generic names the ledger uses."""
    out: dict[str, list[dict[str, Any]]] = {}
    for kind, model in SNAPSHOT_MODELS.items():
        publication_id = model.assurance_id if kind == "model_assurance" else model.publication_id
        identity = model.assurance_identity_sha256 if kind == "model_assurance" else model.publication_identity_sha256
        rows = session.execute(
            select(
                model.id.label("id"),
                publication_id.label("publication_id"),
                identity.label("identity_sha256"),
                model.bundle_sha256.label("bundle_sha256"),
                model.contract_version.label("contract_version"),
                model.schema_version.label("schema_version"),
                model.source_code_commit.label("source_code_commit"),
                model.published_at.label("published_at"),
                model.is_active.label("is_active"),
            )
        ).mappings()
        out[kind] = [dict(row) for row in rows]
    return out


def operational_published_seq(session: Session, identity: str) -> int | None:
    """Seq of the publication.published entry of the operational publication with this identity."""
    subject = session.scalar(
        select(OperationalIntelligenceSnapshot.publication_id).where(
            OperationalIntelligenceSnapshot.publication_identity_sha256 == identity
        )
    )
    if subject is None:
        return None
    return session.scalar(
        select(func.min(TransparencyLedger.seq)).where(
            TransparencyLedger.subject == f"publication:operational_intelligence:{subject}",
            TransparencyLedger.event_type == "publication.published",
        )
    )
