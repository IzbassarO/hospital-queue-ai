"""Transparency ledger: append inside the business transaction, receipts, reads, export and server verification.

Every write function here runs inside the caller's transaction and never commits: a decision or a publication and
its ledger entry are committed together or not at all (docs/transparency-ledger.md §5). Event content comes from
app/domain/transparency, the same builders the server verifier uses (migration 0019 carries a frozen copy).
"""

from __future__ import annotations

import datetime as dt
import secrets
import time
from collections import defaultdict
from collections.abc import Iterator, Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import TransparencyLedger
from app.domain.transparency import chain, events
from app.domain.transparency.canonical import canonical_text, parse_timestamp, timestamp
from app.repositories import transparency as repository
from app.schemas.common import Page
from app.schemas.transparency import (
    LedgerEntry,
    LedgerHead,
    LedgerReceipt,
    LedgerVerification,
    VerificationIssue,
)
from app.services.common import NotFoundError, ValidationError

MAX_ISSUES = 20
LOOKUP_LIMIT = 50


class LedgerBusyError(RuntimeError):
    """Another full-ledger read (verification or export) is running; mapped to HTTP 503 with Retry-After."""


# How long a full-ledger read waits for the one running before it answers 503 (a page loads verification and the
# export together, so they must queue, not fail).
FULL_READ_WAIT_MS = 15_000


def _single_full_read(session: Session) -> None:
    """Full-ledger reads cost memory and time proportional to the ledger: one at a time across every API worker,
    decided by PostgreSQL, so repeated requests queue instead of multiplying that cost (docs/transparency-ledger.md
    §11)."""
    if not repository.lock_full_read(session, FULL_READ_WAIT_MS):
        raise LedgerBusyError("another transparency verification or export is running; retry in a few seconds")


class LedgerNotInitializedError(RuntimeError):
    """The ledger has no genesis: migrations 0018/0019 have not run."""


# ------------------------------------------------------------------------------------------------ mapping
def _entry(row: TransparencyLedger) -> chain.LedgerEntry:
    return chain.LedgerEntry(
        seq=row.seq,
        created_at=timestamp(row.created_at),
        event_type=row.event_type,
        subject=row.subject,
        payload=row.payload,
        prev_hash=row.prev_hash,
        entry_hash=row.entry_hash,
    )


def _response(row: TransparencyLedger) -> LedgerEntry:
    return LedgerEntry(**_entry(row).public())


def _receipt(row: TransparencyLedger) -> LedgerReceipt:
    return LedgerReceipt(
        ledger_seq=row.seq,
        entry_hash=row.entry_hash,
        event_type=row.event_type,
        subject=row.subject,
        created_at=timestamp(row.created_at),
        verify_path=f"/verify?seq={row.seq}",
    )


# ------------------------------------------------------------------------------------------------ writes
def append(session: Session, event: events.Event) -> chain.LedgerEntry:
    """Chain one event onto the committed head, inside the caller's transaction (no commit here)."""
    repository.lock_for_append(session)
    head = repository.head(session)
    if head is None:
        raise LedgerNotInitializedError("transparency_ledger has no genesis entry: run `alembic upgrade head`")
    entry = events.chain_next(_entry(head), event)
    repository.insert(
        session,
        TransparencyLedger(
            seq=entry.seq,
            created_at=parse_timestamp(entry.created_at),
            event_type=entry.event_type,
            subject=entry.subject,
            payload=entry.payload,
            prev_hash=entry.prev_hash,
            entry_hash=entry.entry_hash,
        ),
    )
    return entry


def new_salt(session: Session, subject: str) -> str:
    """A fresh 32-byte salt from the OS CSPRNG, stored privately before the entry that uses it."""
    salt = secrets.token_hex(32)
    repository.insert_salt(session, subject, salt)
    return salt


def _as_receipt(entry: chain.LedgerEntry) -> LedgerReceipt:
    return LedgerReceipt(
        ledger_seq=entry.seq,
        entry_hash=entry.entry_hash,
        event_type=entry.event_type,
        subject=entry.subject,
        created_at=entry.created_at,
        verify_path=f"/verify?seq={entry.seq}",
    )


def record_specialist_decision(session: Session, row: Any) -> LedgerReceipt:
    values = {name: getattr(row, name) for name in repository.SPECIALIST_COLUMNS}
    subject = events.decision_subject(events.SPECIALIST_DECISION, row.id)
    salt = new_salt(session, subject)
    identity = values["publication_identity_sha256"]
    evidence_seq = repository.operational_published_seq(session, identity) if identity else None
    return _as_receipt(append(session, events.specialist_decision(values, salt, evidence_seq)))


def record_hospital_decision(session: Session, row: Any) -> LedgerReceipt:
    values = {name: getattr(row, name) for name in repository.HOSPITAL_COLUMNS}
    subject = events.decision_subject(events.HOSPITAL_DECISION, row.id)
    salt = new_salt(session, subject)
    return _as_receipt(append(session, events.hospital_decision(values, salt)))


def _publication_values(kind: str, snapshot: Any) -> dict[str, Any]:
    assurance = kind == "model_assurance"
    return {
        "id": snapshot.id,
        "publication_id": snapshot.assurance_id if assurance else snapshot.publication_id,
        "identity_sha256": snapshot.assurance_identity_sha256 if assurance else snapshot.publication_identity_sha256,
        "bundle_sha256": snapshot.bundle_sha256,
        "contract_version": snapshot.contract_version,
        "schema_version": snapshot.schema_version,
        "source_code_commit": snapshot.source_code_commit,
        "published_at": snapshot.published_at,
    }


def _now(session: Session) -> dt.datetime:
    """The transaction's own timestamp: the instant every row written in it carries."""
    return session.scalar(select(func.now()))


def record_publication(session: Session, kind: str, previous: Any | None, snapshot: Any) -> None:
    """A new snapshot was inserted and made active: deactivated(previous), published(new), activated(new)."""
    values = _publication_values(kind, snapshot)
    at = values["published_at"]
    if previous is not None and previous.id != snapshot.id:
        append(session, events.activation(events.DEACTIVATED, kind, _publication_values(kind, previous), at))
    append(session, events.published(kind, values))
    append(session, events.activation(events.ACTIVATED, kind, values, at))


def record_activation(session: Session, kind: str, previous: Any | None, snapshot: Any) -> None:
    """An already published snapshot was made active again (idempotent republish). No entry when it already was."""
    if previous is not None and previous.id == snapshot.id:
        return
    at = _now(session)
    if previous is not None:
        append(session, events.activation(events.DEACTIVATED, kind, _publication_values(kind, previous), at))
    append(session, events.activation(events.ACTIVATED, kind, _publication_values(kind, snapshot), at))


# ------------------------------------------------------------------------------------------------ receipts
def decision_receipt(session: Session, kind: str, decision_id: int) -> LedgerReceipt | None:
    subject = events.decision_subject(kind, decision_id)
    row = repository.recorded_for(session, [subject], events.DECISION_RECORDED).get(subject)
    return _receipt(row) if row else None


def decision_receipts(session: Session, kind: str, decision_ids: list[int]) -> dict[int, LedgerReceipt]:
    subjects = {events.decision_subject(kind, i): i for i in decision_ids}
    rows = repository.recorded_for(session, subjects, events.DECISION_RECORDED)
    return {subjects[subject]: _receipt(row) for subject, row in rows.items()}


# ------------------------------------------------------------------------------------------------ reads
def head(session: Session) -> LedgerHead:
    row = repository.head(session)
    if row is None:
        raise NotFoundError("the transparency ledger is empty: run `alembic upgrade head`")
    first = repository.by_seq(session, 1)
    return LedgerHead(
        seq=row.seq,
        entry_hash=row.entry_hash,
        created_at=timestamp(row.created_at),
        chain_length=row.seq,
        genesis_hash=first.entry_hash if first else "",
        protocol=chain.PROTOCOL,
        protocol_version=chain.PROTOCOL_VERSION,
        canonicalization=chain.CANONICALIZATION,
    )


def entries(
    session: Session, *, limit: int, offset: int, descending: bool, event_type: str | None
) -> Page[LedgerEntry]:
    rows, total = repository.page(session, limit=limit, offset=offset, descending=descending, event_type=event_type)
    return Page[LedgerEntry](items=[_response(r) for r in rows], total=total, limit=limit, offset=offset)


def entry(session: Session, seq: int) -> LedgerEntry:
    row = repository.by_seq(session, seq)
    if row is None:
        raise NotFoundError(f"no ledger entry {seq}")
    return _response(row)


def lookup(session: Session, *, entry_hash: str | None, subject: str | None) -> list[LedgerEntry]:
    """Entries by hash (a receipt's full hash, or a prefix of at least 8 hex characters) or by exact subject."""
    if (entry_hash is None) == (subject is None):
        raise ValidationError("give exactly one of entry_hash or subject")
    if entry_hash is not None:
        prefix = entry_hash.strip().lower()
        if not 8 <= len(prefix) <= 64 or any(c not in "0123456789abcdef" for c in prefix):
            raise ValidationError("entry_hash must be 8 to 64 hexadecimal characters")
        rows = repository.by_hash_prefix(session, prefix, LOOKUP_LIMIT)
    else:
        rows = repository.by_subject(session, subject.strip(), LOOKUP_LIMIT)  # type: ignore[union-attr]
    return [_response(r) for r in rows]


def export(session: Session) -> list[str]:
    """The whole public export, read under the single full-read lock (the caller streams it after the session
    closes)."""
    _single_full_read(session)
    return list(export_lines(session))


def export_lines(session: Session) -> Iterator[str]:
    """The public export: one canonical JSON entry per line, in seq order. No salts, no free text."""
    for row in repository.iterate(session):
        yield canonical_text(_entry(row).public()) + "\n"


# ------------------------------------------------------------------------------------------------ server verification
CHECKS = [
    "canonical JSON of every entry (hqai-canonical-json-v1)",
    "protocol v1 genesis, contiguous seq, prev_hash links, recomputed SHA-256 entry hashes",
    "every decision row and publication snapshot has its entry, and each entry still matches its row",
    "salted commitments of every client-supplied field (comment, actor, API-key label, idempotency key, subject, run "
    "and recommendation ids) match the current row",
    "the latest recorded activation state matches the active publications",
]


def _diff(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    keys = sorted(set(expected) | set(actual))
    return [k for k in keys if canonical_text(expected.get(k)) != canonical_text(actual.get(k))]


class _SourceCheck:
    """Compares entries with the current rows they cover."""

    def __init__(self, session: Session) -> None:
        self.specialist = {row["id"]: row for row in repository.specialist_decisions(session)}
        self.hospital = {row["id"]: row for row in repository.hospital_decisions(session)}
        self.publications = {
            kind: {row["id"]: row for row in rows} for kind, rows in repository.publications(session).items()
        }
        self.salts = repository.all_salts(session)
        self.covered: set[str] = set()
        self.operational_seq: dict[str, int] = {}
        # kind → snapshot id → last activation event seen (activated/deactivated) and its seq
        self.activation: dict[str, dict[int, tuple[str, int]]] = defaultdict(dict)
        self.issues: list[VerificationIssue] = []

    def issue(self, seq: int | None, code: str, subject: str | None, detail: str) -> None:
        self.issues.append(VerificationIssue(seq=seq, reason_code=code, subject=subject, detail=detail))

    def _decision(self, entry: chain.LedgerEntry) -> None:
        kind, _, raw_id = entry.subject.partition(":")
        decision_id = int(raw_id) if raw_id.isdigit() else -1
        rows = self.specialist if kind == events.SPECIALIST_DECISION else self.hospital
        row = rows.get(decision_id)
        if row is None:
            self.issue(entry.seq, "SOURCE_ROW_MISSING", entry.subject, "the decision row no longer exists")
            return
        salt = self.salts.get(entry.subject)
        if salt is None:
            self.issue(entry.seq, "SALT_MISSING", entry.subject, "no private commitment salt for this subject")
            return
        if kind == events.SPECIALIST_DECISION:
            identity = row["publication_identity_sha256"]
            expected = events.specialist_decision(row, salt, self.operational_seq.get(identity) if identity else None)
        else:
            expected = events.hospital_decision(row, salt)
        differing = _diff(expected.payload, entry.payload)
        if expected.created_at != entry.created_at:
            differing.append("created_at")
        if not differing:
            return
        commitments = _diff(expected.payload.get("commitments", {}), entry.payload.get("commitments", {}))
        if differing == ["commitments"]:
            self.issue(
                entry.seq,
                "COMMITMENT_MISMATCH",
                entry.subject,
                f"current value of {', '.join(commitments)} does not match the committed value",
            )
        else:
            self.issue(entry.seq, "SOURCE_FIELD_MISMATCH", entry.subject, f"row differs in {', '.join(differing)}")

    def _publication(self, entry: chain.LedgerEntry) -> None:
        kind = entry.payload.get("publication_kind")
        snapshot_id = entry.payload.get("snapshot_id")
        rows = self.publications.get(kind) if isinstance(kind, str) else None
        if rows is None:
            self.issue(entry.seq, "PUBLICATION_MISMATCH", entry.subject, "unknown publication kind")
            return
        row = rows.get(snapshot_id) if isinstance(snapshot_id, int) else None
        if row is None:
            self.issue(entry.seq, "SOURCE_ROW_MISSING", entry.subject, "the publication snapshot no longer exists")
            return
        if entry.event_type == events.PUBLISHED:
            expected = events.published(kind, row)
            differing = _diff(expected.payload, entry.payload)
            if expected.created_at != entry.created_at:
                differing.append("created_at")
            if expected.subject != entry.subject:
                differing.append("subject")
            if differing:
                self.issue(
                    entry.seq, "PUBLICATION_MISMATCH", entry.subject, f"snapshot differs in {', '.join(differing)}"
                )
            if kind == "operational_intelligence":
                self.operational_seq.setdefault(row["identity_sha256"], entry.seq)
        else:
            expected = events.activation(entry.event_type, kind, row, dt.datetime.now(dt.UTC))
            differing = _diff(expected.payload, entry.payload)
            if expected.subject != entry.subject:
                differing.append("subject")
            if differing:
                self.issue(
                    entry.seq, "PUBLICATION_MISMATCH", entry.subject, f"snapshot differs in {', '.join(differing)}"
                )
            self.activation[kind][row["id"]] = (entry.event_type, entry.seq)

    def add(self, entry: chain.LedgerEntry) -> None:
        if entry.event_type == chain.GENESIS_EVENT:
            return
        if entry.event_type in events.ONCE_PER_SUBJECT:
            key = f"{entry.event_type}|{entry.subject}"
            if key in self.covered:
                self.issue(entry.seq, "DUPLICATE_SUBJECT_EVENT", entry.subject, f"second {entry.event_type} entry")
                return
            self.covered.add(key)
        if entry.event_type == events.DECISION_RECORDED:
            self._decision(entry)
        elif entry.event_type in (events.PUBLISHED, events.ACTIVATED, events.DEACTIVATED):
            self._publication(entry)
        else:
            self.issue(entry.seq, "UNKNOWN_EVENT_TYPE", entry.subject, f"{entry.event_type} is not a v1 event")

    def finish(self) -> None:
        for kind, rows in (
            (events.SPECIALIST_DECISION, self.specialist),
            (events.HOSPITAL_DECISION, self.hospital),
        ):
            for decision_id in sorted(rows):
                subject = events.decision_subject(kind, decision_id)
                if f"{events.DECISION_RECORDED}|{subject}" not in self.covered:
                    self.issue(None, "UNCOVERED_SOURCE_ROW", subject, "decision row without a ledger entry")
        for kind, rows in self.publications.items():
            for row in sorted(rows.values(), key=lambda r: r["id"]):
                subject = events.publication_subject(kind, row["publication_id"])
                if f"{events.PUBLISHED}|{subject}" not in self.covered:
                    self.issue(None, "UNCOVERED_SOURCE_ROW", subject, "publication snapshot without a ledger entry")
            state = self.activation.get(kind, {})
            active = {row["id"] for row in rows.values() if row["is_active"]}
            recorded_active = {sid for sid, (event_type, _) in state.items() if event_type == events.ACTIVATED}
            deactivated_but_active = [sid for sid in active if state.get(sid, ("", 0))[0] == events.DEACTIVATED]
            mismatch = (recorded_active and recorded_active != active) or deactivated_but_active
            if mismatch:
                last_seq = max(seq for _, seq in state.values())
                subject_ids = sorted(recorded_active ^ active) or deactivated_but_active
                names = [rows[sid]["publication_id"] for sid in subject_ids if sid in rows]
                self.issue(
                    last_seq,
                    "ACTIVE_STATE_MISMATCH",
                    events.publication_subject(kind, names[0]) if names else None,
                    "the active publication differs from the last recorded activation",
                )


def verify(session: Session) -> LedgerVerification:
    """Server verification (docs/transparency-ledger.md §7): the public chain, then every covered source row."""
    _single_full_read(session)
    started = time.perf_counter()
    verifier = chain.ChainVerifier()
    sources = _SourceCheck(session)
    stored_head = repository.head(session)
    stored = session.scalar(select(func.count()).select_from(TransparencyLedger)) or 0
    for row in repository.iterate(session):
        current = _entry(row)
        if verifier.failure is None:
            verifier.add(current)
        # rows are compared with their entries even past a chain break, so coverage is not misreported
        sources.add(current)
    result = verifier.finish()
    sources.finish()
    issues = list(sources.issues)
    if result.failure is not None:
        issues.append(
            VerificationIssue(
                seq=result.failure.seq,
                reason_code=result.failure.reason_code,
                subject=result.failure.subject,
                detail=result.failure.detail,
            )
        )
    issues.sort(key=lambda i: (i.seq is None, i.seq or 0))
    first = issues[0] if issues else None
    verified_through = result.verified_through_seq
    if first is not None:
        verified_through = min(verified_through, first.seq - 1) if first.seq is not None else verified_through
    return LedgerVerification(
        status="OK" if first is None else "BROKEN",
        verified_at=dt.datetime.now(dt.UTC),
        duration_ms=round((time.perf_counter() - started) * 1000),
        chain_length=stored,
        verified_through_seq=verified_through,
        head_seq=stored_head.seq if stored_head else None,
        head_hash=stored_head.entry_hash if stored_head else None,
        failure_seq=first.seq if first else None,
        reason_code=first.reason_code if first else None,
        subject=first.subject if first else None,
        issues=issues[:MAX_ISSUES],
        covered_decisions=len(sources.specialist) + len(sources.hospital),
        covered_publications=sum(len(rows) for rows in sources.publications.values()),
        checks=CHECKS,
    )
