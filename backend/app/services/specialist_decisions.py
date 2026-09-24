"""Specialist decisions of the control centre: stored as typed rows, replayed on reload of the demo."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import SpecialistDecision as Row
from app.schemas.common import Page
from app.schemas.specialist import SpecialistDecision, SpecialistDecisionCreate
from app.services.common import ConflictError

ALERT_ACTIONS = {"accept", "decline", "clarify"}
PATIENT_ACTIONS = {"confirm", "decline", "postpone"}


def _decision(row: Row) -> SpecialistDecision:
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
    )


def create_decision(
    session: Session, payload: SpecialistDecisionCreate, api_key_label: str
) -> tuple[SpecialistDecision, bool]:
    """Store a decision; (decision, created). A stored idempotency_key replays the row (created = False) when the
    content matches and conflicts (409) when it does not. The action must fit the subject kind (422)."""
    allowed = ALERT_ACTIONS if payload.subject_kind == "alert" else PATIENT_ACTIONS
    if payload.action not in allowed:
        from app.services.common import ValidationError

        raise ValidationError(
            f"action {payload.action!r} is not valid for subject_kind {payload.subject_kind!r} "
            f"(allowed: {', '.join(sorted(allowed))})"
        )
    if payload.idempotency_key:
        existing = session.scalar(select(Row).where(Row.idempotency_key == payload.idempotency_key))
        if existing is not None:
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
            return stored, False
    row = Row(
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
    session.commit()
    session.refresh(row)
    return _decision(row), True


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
    return Page[SpecialistDecision](items=[_decision(r) for r in rows], total=total, limit=limit, offset=offset)
