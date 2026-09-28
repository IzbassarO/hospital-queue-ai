"""Queries for the published verification worklist read model.

The worklist rows carry no patient data of their own: they are joined to the measured queue at read time for the
registration date and the operational code the bureau needs to look a record up. That join is an OUTER join — a
referral the current waiting-list publication no longer carries still appears, with those two fields null, rather
than silently dropping off a list someone is working through.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DimOrganization,
    DimProfile,
    DimRegion,
    VerificationWorklistArea,
    VerificationWorklistItem,
    WaitingListReferral,
)
from app.db.models import VerificationWorklistSnapshot as Snapshot


def current_snapshot(session: Session, *, for_update: bool = False) -> Snapshot | None:
    query = select(Snapshot).where(Snapshot.is_active.is_(True))
    if for_update:
        query = query.with_for_update()
    return session.scalar(query)


def snapshot_by_publication_id(session: Session, publication_id: str) -> Snapshot | None:
    return session.scalar(select(Snapshot).where(Snapshot.publication_id == publication_id))


def snapshot_by_identity(session: Session, identity: str) -> Snapshot | None:
    return session.scalar(select(Snapshot).where(Snapshot.publication_identity_sha256 == identity))


def area(session: Session, snapshot_id: int, level: str, code: str) -> VerificationWorklistArea | None:
    row = VerificationWorklistArea
    return session.scalar(select(row).where(row.snapshot_id == snapshot_id, row.level == level, row.code == code))


def areas(session: Session, snapshot_id: int, level: str) -> list[tuple[VerificationWorklistArea, str | None]]:
    """Area rows of one level, largest formal queue first, with the region name for the region view."""
    row = VerificationWorklistArea
    query = (
        select(row, DimRegion.region_name)
        .outerjoin(DimRegion, DimRegion.region_code == row.code)
        .where(row.snapshot_id == snapshot_id, row.level == level)
        .order_by(row.formal_queue_count.desc(), row.code)
    )
    return [tuple(item) for item in session.execute(query).all()]


def _item_query(snapshot_id: int, org_code: str, waiting_snapshot_id: int | None, *, warning: bool | None) -> Select:
    item = VerificationWorklistItem
    queue = WaitingListReferral
    join_on = (queue.referral_id == item.referral_id) & (queue.snapshot_id == waiting_snapshot_id)
    query = (
        select(item, DimProfile.profile_name, queue.registration_date, queue.hospitalization_code)
        .outerjoin(DimProfile, DimProfile.profile_code == item.profile_code)
        .outerjoin(queue, join_on)
        .where(item.snapshot_id == snapshot_id, item.org_code == org_code)
    )
    if warning is not None:
        query = query.where(item.history_quality_warning.is_(warning))
    return query


def count_items(
    session: Session, snapshot_id: int, org_code: str, waiting_snapshot_id: int | None, *, warning: bool | None = None
) -> int:
    query = _item_query(snapshot_id, org_code, waiting_snapshot_id, warning=warning)
    return session.scalar(select(func.count()).select_from(query.subquery())) or 0


def items(
    session: Session,
    snapshot_id: int,
    org_code: str,
    waiting_snapshot_id: int | None,
    *,
    warning: bool | None = None,
    order: str,
    limit: int,
    offset: int,
) -> list[tuple]:
    item = VerificationWorklistItem
    query = _item_query(snapshot_id, org_code, waiting_snapshot_id, warning=warning)
    ordering = (item.days_waited_at_origin.desc(), item.rank) if order == "longest_wait" else (item.rank,)
    return [tuple(row) for row in session.execute(query.order_by(*ordering).limit(limit).offset(offset)).all()]


def organization_name(session: Session, org_code: str) -> tuple[str, str, str] | None:
    """(org_name, region_code, region_name) for one hospital, or None when the registry does not know it."""
    result = session.execute(
        select(DimOrganization.org_name, DimOrganization.region_code, DimRegion.region_name)
        .outerjoin(DimRegion, DimRegion.region_code == DimOrganization.region_code)
        .where(DimOrganization.org_code == org_code)
    ).first()
    return tuple(result) if result is not None else None
