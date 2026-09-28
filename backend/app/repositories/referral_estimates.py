"""Queries for the published per-referral estimate read model, and its join onto the measured queue.

The queue rows and the estimates come from two different publications. Every query here is scoped to one snapshot
id of each, and the estimate side is an OUTER join: a referral the estimate publication does not cover keeps its
measured row and shows no number, which is the honest rendering of "not estimated".
"""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import DimProfile, ReferralEstimate, WaitingListReferral
from app.db.models import ReferralEstimateSnapshot as Snapshot


def current_snapshot(session: Session, *, for_update: bool = False) -> Snapshot | None:
    query = select(Snapshot).where(Snapshot.is_active.is_(True))
    if for_update:
        query = query.with_for_update()
    return session.scalar(query)


def snapshot_by_publication_id(session: Session, publication_id: str) -> Snapshot | None:
    return session.scalar(select(Snapshot).where(Snapshot.publication_id == publication_id))


def snapshot_by_identity(session: Session, identity: str) -> Snapshot | None:
    return session.scalar(select(Snapshot).where(Snapshot.publication_identity_sha256 == identity))


def _queue_query(
    waiting_snapshot_id: int,
    estimate_snapshot_id: int | None,
    org_code: str,
    *,
    profile_code: str | None = None,
    attention_only: bool = False,
) -> Select:
    """Measured queue rows of one hospital, each with its estimate when one is published."""
    row = WaitingListReferral
    estimate = ReferralEstimate
    join_on = (estimate.referral_id == row.referral_id) & (estimate.snapshot_id == estimate_snapshot_id)
    query = (
        select(row, DimProfile.profile_name, estimate)
        .outerjoin(DimProfile, DimProfile.profile_code == row.profile_code)
        .outerjoin(estimate, join_on)
        .where(row.snapshot_id == waiting_snapshot_id, row.org_code == org_code)
    )
    if profile_code is not None:
        query = query.where(row.profile_code == profile_code)
    if attention_only:
        query = query.where(estimate.refusal_attention.is_(True))
    return query


def count_queue(
    session: Session,
    waiting_snapshot_id: int,
    estimate_snapshot_id: int | None,
    org_code: str,
    *,
    profile_code: str | None = None,
    attention_only: bool = False,
) -> int:
    query = _queue_query(
        waiting_snapshot_id,
        estimate_snapshot_id,
        org_code,
        profile_code=profile_code,
        attention_only=attention_only,
    )
    return session.scalar(select(func.count()).select_from(query.subquery())) or 0


def queue(
    session: Session,
    waiting_snapshot_id: int,
    estimate_snapshot_id: int | None,
    org_code: str,
    *,
    profile_code: str | None = None,
    attention_only: bool = False,
    order: str,
    limit: int,
    offset: int,
) -> list[tuple[WaitingListReferral, str | None, ReferralEstimate | None]]:
    row = WaitingListReferral
    query = _queue_query(
        waiting_snapshot_id,
        estimate_snapshot_id,
        org_code,
        profile_code=profile_code,
        attention_only=attention_only,
    )
    if order == "highest_refusal_risk":
        # NULLS LAST: a referral with no estimate is not "low risk", it is unknown, and it belongs after the
        # referrals the administrator can actually act on.
        ordering = (ReferralEstimate.refused_30d.desc().nullslast(), row.days_waited_at_origin.desc())
    elif order == "shortest_wait":
        ordering = (row.days_waited_at_origin.asc(),)
    else:
        ordering = (row.days_waited_at_origin.desc(),)
    query = query.order_by(*ordering, row.referral_id).limit(limit).offset(offset)
    return [tuple(item) for item in session.execute(query).all()]
