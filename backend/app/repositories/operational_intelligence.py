"""Queries for published operational-intelligence read models."""

import datetime as dt

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session, aliased

from app.db.models import OperationalForecast, OperationalIntelligenceSnapshot, OperationalSignal


def current_snapshot(session: Session, *, for_update: bool = False) -> OperationalIntelligenceSnapshot | None:
    query = select(OperationalIntelligenceSnapshot).where(OperationalIntelligenceSnapshot.is_active.is_(True))
    if for_update:
        query = query.with_for_update()
    return session.scalar(query)


def snapshot_by_publication_id(session: Session, publication_id: str) -> OperationalIntelligenceSnapshot | None:
    return session.scalar(
        select(OperationalIntelligenceSnapshot).where(OperationalIntelligenceSnapshot.publication_id == publication_id)
    )


def snapshot_by_identity(session: Session, identity: str) -> OperationalIntelligenceSnapshot | None:
    return session.scalar(
        select(OperationalIntelligenceSnapshot).where(
            OperationalIntelligenceSnapshot.publication_identity_sha256 == identity
        )
    )


def _signal_query(
    snapshot_id: int,
    *,
    region_code: str | None = None,
    org_code: str | None = None,
    profile_code: str | None = None,
    target: str | None = None,
    severity: str | None = None,
    signal_type: str | None = None,
    support_status: str | None = None,
    materiality_status: str | None = None,
) -> Select:
    row = OperationalSignal
    query = select(row).where(row.snapshot_id == snapshot_id)
    filters = (
        (row.region_code, region_code),
        (row.org_code, org_code),
        (row.profile_code, profile_code),
        (row.target, target),
        (row.severity, severity),
        (row.signal_type, signal_type),
        (row.support_status, support_status),
        (row.materiality_status, materiality_status),
    )
    for column, value in filters:
        if value is not None:
            query = query.where(column == value)
    severity_order = case(
        {"HIGH": 0, "ELEVATED": 1, "WATCH": 2, "NORMAL": 3, "UNSUPPORTED": 4},
        value=row.severity,
        else_=5,
    )
    return query.order_by(row.inbox_rank.asc().nulls_last(), severity_order, row.signal_id)


def signals(
    session: Session,
    snapshot_id: int,
    *,
    region_code: str | None = None,
    org_code: str | None = None,
    profile_code: str | None = None,
    target: str | None = None,
    severity: str | None = None,
    signal_type: str | None = None,
    support_status: str | None = None,
    materiality_status: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[OperationalSignal], int]:
    query = _signal_query(
        snapshot_id,
        region_code=region_code,
        org_code=org_code,
        profile_code=profile_code,
        target=target,
        severity=severity,
        signal_type=signal_type,
        support_status=support_status,
        materiality_status=materiality_status,
    )
    count_query = select(func.count()).select_from(query.order_by(None).subquery())
    total = session.scalar(count_query) or 0
    rows = list(session.scalars(query.limit(limit).offset(offset)).all())
    return rows, total


def signal(session: Session, snapshot_id: int, signal_id: str) -> OperationalSignal | None:
    return session.scalar(
        select(OperationalSignal).where(
            OperationalSignal.snapshot_id == snapshot_id,
            OperationalSignal.signal_id == signal_id,
        )
    )


def signal_summary_rows(session: Session, snapshot_id: int, region_code: str | None = None):
    row = OperationalSignal
    query = (
        select(
            row.region_code,
            row.severity,
            row.signal_type,
            row.support_status,
            row.uncertainty_status,
            func.count().label("count"),
        )
        .where(row.snapshot_id == snapshot_id)
        .group_by(
            row.region_code,
            row.severity,
            row.signal_type,
            row.support_status,
            row.uncertainty_status,
        )
    )
    if region_code is not None:
        query = query.where(row.region_code == region_code)
    return session.execute(query).all()


def forecasts(
    session: Session,
    snapshot_id: int,
    *,
    origin: dt.date | None = None,
    target_date_from: dt.date | None = None,
    target_date_to: dt.date | None = None,
    level: str | None = None,
    region_code: str | None = None,
    org_code: str | None = None,
    profile_code: str | None = None,
    target: str | None = None,
    limit: int,
    offset: int,
) -> tuple[list[OperationalForecast], int]:
    row = OperationalForecast
    query = select(row).where(row.snapshot_id == snapshot_id)
    equals = (
        (row.origin, origin),
        (row.level, level),
        (row.region_code, region_code),
        (row.org_code, org_code),
        (row.profile_code, profile_code),
        (row.target, target),
    )
    for column, value in equals:
        if value is not None:
            query = query.where(column == value)
    if target_date_from is not None:
        query = query.where(row.target_date >= target_date_from)
    if target_date_to is not None:
        query = query.where(row.target_date <= target_date_to)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    query = query.order_by(row.origin.desc(), row.target, row.level, row.series_id, row.target_date)
    return list(session.scalars(query.limit(limit).offset(offset)).all()), total


def hospital_forecast_facets(
    session: Session, snapshot_id: int, org_code: str, profile_code: str
) -> tuple[int, list[dt.date], list[str], str | None]:
    row = OperationalForecast
    where = (
        row.snapshot_id == snapshot_id,
        row.org_code == org_code,
        row.profile_code == profile_code,
    )
    count = session.scalar(select(func.count()).select_from(row).where(*where)) or 0
    origins = list(session.scalars(select(row.origin).where(*where).distinct().order_by(row.origin)).all())
    targets = list(session.scalars(select(row.target).where(*where).distinct().order_by(row.target)).all())
    region_code = session.scalar(select(row.region_code).where(*where, row.region_code.is_not(None)).limit(1))
    return count, origins, targets, region_code


def region_forecast_facets(
    session: Session, snapshot_id: int, region_code: str
) -> tuple[int, list[dt.date], list[str]]:
    row = OperationalForecast
    where = (row.snapshot_id == snapshot_id, row.region_code == region_code)
    count = session.scalar(select(func.count()).select_from(row).where(*where)) or 0
    origins = list(session.scalars(select(row.origin).where(*where).distinct().order_by(row.origin)).all())
    targets = list(session.scalars(select(row.target).where(*where).distinct().order_by(row.target)).all())
    return count, origins, targets


def forecast_regions(session: Session, snapshot_id: int) -> list[str]:
    """The distinct region codes of one publication's forecasts, in order.

    A plain `SELECT DISTINCT` reads every row of the snapshot to find twenty values: on the released publication
    that was a parallel sequential scan over 305 MB, ~250 MB of buffers per request, which exhausts the page cache
    of a small server and trips `statement_timeout` as soon as a few requests overlap.

    This walks the index instead — smallest code, then repeatedly the smallest code above the last one — so it
    costs one index probe per region (21 probes, ~70 buffers) rather than one pass per row. PostgreSQL 16 has no
    loose index scan of its own, so the walk is written out as a recursive CTE. The result is the same set in the
    same order; only the way it is reached changes. Needs ix_operational_forecast_region_facets (migration 0015).
    """
    row = OperationalForecast
    smallest = (
        select(row.region_code)
        .where(row.snapshot_id == snapshot_id, row.region_code.is_not(None))
        .order_by(row.region_code)
        .limit(1)
    )
    walk = smallest.cte("region_walk", recursive=True)
    nxt = aliased(OperationalForecast)
    after = (
        select(nxt.region_code)
        .where(nxt.snapshot_id == snapshot_id, nxt.region_code > walk.c.region_code)
        .order_by(nxt.region_code)
        .limit(1)
        .scalar_subquery()
    )
    # the walk ends when no code is left above the last one, which appends one NULL row and stops the recursion
    walk = walk.union_all(select(after).select_from(walk).where(walk.c.region_code.is_not(None)))
    return list(
        session.scalars(
            select(walk.c.region_code).where(walk.c.region_code.is_not(None)).order_by(walk.c.region_code)
        ).all()
    )
