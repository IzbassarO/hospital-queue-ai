"""Specialist decisions of the control centre: stored as typed rows, replayed on reload of the demo.

Every stored decision carries the identity of the operational-intelligence publication that was active when it was
written, so a decision can later be read against the evidence the person actually saw (the client cannot set it).
The decision and its transparency-ledger entry are written in one transaction (docs/transparency-ledger.md §5): the
response carries the entry as a receipt, and an idempotent replay returns the original receipt.
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import SpecialistDecision as Row
from app.domain.transparency.events import SPECIALIST_DECISION
from app.repositories import operational_intelligence as operational_repository
from app.schemas.common import Page
from app.schemas.specialist import SpecialistDecision, SpecialistDecisionCreate
from app.services import transparency
from app.services.common import ConflictError, ValidationError

ALERT_ACTIONS = {"accept", "decline", "clarify"}
PATIENT_ACTIONS = {"confirm", "decline", "postpone"}


def _decision(row: Row, receipt=None) -> SpecialistDecision:
    return SpecialistDecision(
        id=row.id,
        created_at=row.created_at,
        origin=row.origin,
        run_id=row.run_id,
        sim_day=row.sim_day,
        subject_kind=row.subject_kind,  # type: ignore[arg-type]
        subject_id=row.subject_id,
        region_code=row.region_code,
        org_code=row.org_code,
        profile_code=row.profile_code,
        action=row.action,  # type: ignore[arg-type]
        comment=row.comment,
        actor=row.actor,
        idempotency_key=row.idempotency_key,
        api_key_label=row.api_key_label,
        publication_identity_sha256=row.publication_identity_sha256,
        receipt=receipt,
    )


def create_decision(
    session: Session, payload: SpecialistDecisionCreate, api_key_label: str
) -> tuple[SpecialistDecision, bool]:
    """Store a decision; (decision, created). A stored idempotency_key replays the row (created = False) when the
    content matches and conflicts (409) when it does not; the publication identity is not part of that comparison,
    a replay returns the row as first stored. The action must fit the subject kind (422)."""
    allowed = ALERT_ACTIONS if payload.subject_kind == "alert" else PATIENT_ACTIONS
    if payload.action not in allowed:
        raise ValidationError(
            f"action {payload.action!r} is not valid for subject_kind {payload.subject_kind!r} "
            f"(allowed: {', '.join(sorted(allowed))})"
        )
    if payload.idempotency_key:
        existing = session.scalar(select(Row).where(Row.idempotency_key == payload.idempotency_key))
        if existing is not None:
            return _replay(session, existing, payload), False
    snapshot = operational_repository.current_snapshot(session)
    row = Row(
        publication_identity_sha256=snapshot.publication_identity_sha256 if snapshot else None,
        origin=payload.origin,
        run_id=payload.run_id,
        sim_day=payload.sim_day,
        subject_kind=payload.subject_kind,
        subject_id=payload.subject_id,
        region_code=payload.region_code,
        org_code=payload.org_code,
        profile_code=payload.profile_code,
        action=payload.action,
        comment=payload.comment,
        actor=payload.actor,
        api_key_label=api_key_label,
        idempotency_key=payload.idempotency_key,
    )
    session.add(row)
    try:
        session.flush()
        receipt = transparency.record_specialist_decision(session, row)
        session.commit()
    except IntegrityError:
        # a concurrent request with the same idempotency_key won the race; its ledger entry is the only one, ours
        # was rolled back with our row
        session.rollback()
        existing = session.scalar(select(Row).where(Row.idempotency_key == payload.idempotency_key))
        if existing is None or payload.idempotency_key is None:
            raise
        return _replay(session, existing, payload), False
    return _decision(row, receipt), True


def _replay(session: Session, existing: Row, payload: SpecialistDecisionCreate) -> SpecialistDecision:
    """The stored decision with its original receipt, or 409 when the same key carries a different decision."""
    stored = _decision(existing)
    differing = [
        name
        for name in ("origin", "run_id", "sim_day", "subject_kind", "subject_id", "action", "comment")
        if getattr(stored, name) != getattr(payload, name)
    ]
    if differing:
        raise ConflictError(
            f"idempotency_key {payload.idempotency_key!r} was already used for a different decision "
            f"(fields differ: {', '.join(differing)})"
        )
    return _decision(existing, transparency.decision_receipt(session, SPECIALIST_DECISION, existing.id))


def list_decisions(
    session: Session,
    origin,
    run_id: str | None,
    subject_kind: str | None,
    limit: int,
    offset: int,
) -> Page[SpecialistDecision]:
    where = []
    if origin is not None:
        where.append(Row.origin == origin)
    if run_id is not None:
        where.append(Row.run_id == run_id)
    if subject_kind is not None:
        where.append(Row.subject_kind == subject_kind)
    total = session.scalar(select(func.count()).select_from(Row).where(*where)) or 0
    rows = session.scalars(
        select(Row).where(*where).order_by(Row.created_at.desc(), Row.id.desc()).limit(limit).offset(offset)
    ).all()
    receipts = transparency.decision_receipts(session, SPECIALIST_DECISION, [r.id for r in rows])
    return Page[SpecialistDecision](
        items=[_decision(r, receipts.get(r.id)) for r in rows], total=total, limit=limit, offset=offset
    )
