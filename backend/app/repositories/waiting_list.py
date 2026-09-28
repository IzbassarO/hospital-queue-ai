"""Queries for the published waiting-list read model.

Every query is scoped to one snapshot id. The observed_* columns are hindsight and are selected for display only:
no query here filters, orders or ranks by them, and none may start to — see app/schemas/waiting_list.py.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import DimOrganization, DimProfile, DimRegion, WaitingListHospital, WaitingListReferral
from app.db.models import WaitingListSnapshot as Snapshot


def current_snapshot(session: Session, *, for_update: bool = False) -> Snapshot | None:
    query = select(Snapshot).where(Snapshot.is_active.is_(True))
    if for_update:
        query = query.with_for_update()
    return session.scalar(query)


def snapshot_by_publication_id(session: Session, publication_id: str) -> Snapshot | None:
    return session.scalar(select(Snapshot).where(Snapshot.publication_id == publication_id))


def snapshot_by_identity(session: Session, identity: str) -> Snapshot | None:
    return session.scalar(select(Snapshot).where(Snapshot.publication_identity_sha256 == identity))


def _hospital_query(
    snapshot_id: int,
    *,
    region_code: str | None = None,
    support_class: str | None = None,
    min_waiting: int | None = None,
) -> Select:
    row = WaitingListHospital
    query = (
        select(row, DimOrganization.org_name, DimRegion.region_name)
        .join(DimOrganization, DimOrganization.org_code == row.org_code)
        .join(DimRegion, DimRegion.region_code == row.region_code)
        .where(row.snapshot_id == snapshot_id)
    )
    if region_code is not None:
        query = query.where(row.region_code == region_code)
    if support_class is not None:
        query = query.where(row.support_class == support_class)
    if min_waiting is not None:
        query = query.where(row.waiting_count >= min_waiting)
    return query


def count_hospitals(
    session: Session,
    snapshot_id: int,
    *,
    region_code: str | None = None,
    support_class: str | None = None,
    min_waiting: int | None = None,
) -> int:
    query = _hospital_query(snapshot_id, region_code=region_code, support_class=support_class, min_waiting=min_waiting)
    return session.scalar(select(func.count()).select_from(query.subquery())) or 0


def hospitals(
    session: Session,
    snapshot_id: int,
    *,
    region_code: str | None = None,
    support_class: str | None = None,
    min_waiting: int | None = None,
    limit: int,
    offset: int,
) -> list[tuple[WaitingListHospital, str, str]]:
    row = WaitingListHospital
    query = (
        _hospital_query(snapshot_id, region_code=region_code, support_class=support_class, min_waiting=min_waiting)
        .order_by(row.waiting_count.desc(), row.org_code)
        .limit(limit)
        .offset(offset)
    )
    return [tuple(item) for item in session.execute(query).all()]


def hospital(session: Session, snapshot_id: int, org_code: str) -> tuple[WaitingListHospital, str, str] | None:
    row = WaitingListHospital
    result = session.execute(
        select(row, DimOrganization.org_name, DimRegion.region_name)
        .join(DimOrganization, DimOrganization.org_code == row.org_code)
        .join(DimRegion, DimRegion.region_code == row.region_code)
        .where(row.snapshot_id == snapshot_id, row.org_code == org_code)
    ).first()
    return tuple(result) if result is not None else None


def _referral_query(snapshot_id: int, org_code: str, *, profile_code: str | None = None) -> Select:
    row = WaitingListReferral
    query = (
        select(row, DimProfile.profile_name)
        .outerjoin(DimProfile, DimProfile.profile_code == row.profile_code)
        .where(row.snapshot_id == snapshot_id, row.org_code == org_code)
    )
    if profile_code is not None:
        query = query.where(row.profile_code == profile_code)
    return query


def count_referrals(session: Session, snapshot_id: int, org_code: str, *, profile_code: str | None = None) -> int:
    query = _referral_query(snapshot_id, org_code, profile_code=profile_code)
    return session.scalar(select(func.count()).select_from(query.subquery())) or 0


def referrals(
    session: Session,
    snapshot_id: int,
    org_code: str,
    *,
    profile_code: str | None = None,
    ascending: bool = False,
    limit: int,
    offset: int,
) -> list[tuple[WaitingListReferral, str | None]]:
    row = WaitingListReferral
    days = row.days_waited_at_origin.asc() if ascending else row.days_waited_at_origin.desc()
    query = (
        _referral_query(snapshot_id, org_code, profile_code=profile_code)
        .order_by(days, row.referral_id)
        .limit(limit)
        .offset(offset)
    )
    return [tuple(item) for item in session.execute(query).all()]


# Days-already-waited histogram edges: [from, to) in days, the last bucket open-ended. Chosen to match how a
# specialist reads a queue (same week / this month / over a month), not a model's time bins.
DAYS_BUCKETS: tuple[tuple[int, int | None], ...] = ((0, 3), (3, 7), (7, 14), (14, 30), (30, 60), (60, None))


def profile_breakdown(
    session: Session, snapshot_id: int, org_code: str
) -> list[tuple[str, str | None, int, float, int]]:
    """(profile_code, profile_name, waiting_count, median_days_waited, max_days_waited), largest queue first."""
    row = WaitingListReferral
    median = func.percentile_cont(0.5).within_group(row.days_waited_at_origin.asc())
    query = (
        select(
            row.profile_code,
            DimProfile.profile_name,
            func.count().label("waiting_count"),
            median.label("median_days"),
            func.max(row.days_waited_at_origin).label("max_days"),
        )
        .outerjoin(DimProfile, DimProfile.profile_code == row.profile_code)
        .where(row.snapshot_id == snapshot_id, row.org_code == org_code)
        .group_by(row.profile_code, DimProfile.profile_name)
        .order_by(func.count().desc(), row.profile_code)
    )
    return [tuple(item) for item in session.execute(query).all()]


def days_waited_histogram(session: Session, snapshot_id: int, org_code: str) -> list[int]:
    """One count per bucket of DAYS_BUCKETS, in that order."""
    row = WaitingListReferral
    columns = [
        func.count().filter(
            row.days_waited_at_origin >= low
            if high is None
            else (row.days_waited_at_origin >= low) & (row.days_waited_at_origin < high)
        )
        for low, high in DAYS_BUCKETS
    ]
    result = session.execute(select(*columns).where(row.snapshot_id == snapshot_id, row.org_code == org_code)).one()
    return [int(value) for value in result]


def observed_counts(session: Session, snapshot_id: int, org_code: str) -> dict[str, int]:
    """Hindsight totals for one hospital. Display only — nothing ranks or filters on these."""
    row = WaitingListReferral
    result = session.execute(
        select(row.observed_status, func.count())
        .where(row.snapshot_id == snapshot_id, row.org_code == org_code)
        .group_by(row.observed_status)
    ).all()
    return {status: int(count) for status, count in result}
