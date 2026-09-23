"""Queries for published review-evidence read models (stress tests, decision alternatives)."""

import datetime as dt

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    OperationalForecast,
    OperationalIntelligenceSnapshot,
    ReviewAlternative,
    ReviewAlternativeSet,
    ReviewEvidenceSnapshot,
    ReviewScenario,
    ReviewScenarioCell,
    ReviewScenarioEntity,
)


def current_snapshot(session: Session, *, for_update: bool = False) -> ReviewEvidenceSnapshot | None:
    query = select(ReviewEvidenceSnapshot).where(ReviewEvidenceSnapshot.is_active.is_(True))
    if for_update:
        query = query.with_for_update()
    return session.scalar(query)


def snapshot_by_publication_id(session: Session, publication_id: str) -> ReviewEvidenceSnapshot | None:
    return session.scalar(select(ReviewEvidenceSnapshot).where(ReviewEvidenceSnapshot.publication_id == publication_id))


def snapshot_by_identity(session: Session, identity: str) -> ReviewEvidenceSnapshot | None:
    return session.scalar(
        select(ReviewEvidenceSnapshot).where(ReviewEvidenceSnapshot.publication_identity_sha256 == identity)
    )


def scenarios(session: Session, snapshot_id: int) -> list[ReviewScenario]:
    return list(
        session.scalars(
            select(ReviewScenario)
            .where(ReviewScenario.snapshot_id == snapshot_id)
            .order_by(ReviewScenario.multiplier.asc().nulls_first(), ReviewScenario.scenario_id)
        ).all()
    )


def entities_for_signal(session: Session, snapshot_id: int, signal_id: str) -> list[ReviewScenarioEntity]:
    return list(
        session.scalars(
            select(ReviewScenarioEntity)
            .where(ReviewScenarioEntity.snapshot_id == snapshot_id, ReviewScenarioEntity.signal_id == signal_id)
            .order_by(ReviewScenarioEntity.scenario_id)
        ).all()
    )


def cells_for_series(
    session: Session, snapshot_id: int, series_id: str, target: str, origin: dt.date
) -> list[ReviewScenarioCell]:
    row = ReviewScenarioCell
    return list(
        session.scalars(
            select(row)
            .where(
                row.snapshot_id == snapshot_id,
                row.series_id == series_id,
                row.target == target,
                row.origin == origin,
            )
            .order_by(row.scenario_id, row.target_date)
        ).all()
    )


def _set_query(
    snapshot_id: int,
    *,
    origin: dt.date | None = None,
    region_code: str | None = None,
    org_code: str | None = None,
    profile_code: str | None = None,
    signal_id: str | None = None,
    with_alternatives: bool | None = None,
) -> Select:
    row = ReviewAlternativeSet
    query = select(row).where(row.snapshot_id == snapshot_id)
    for column, value in (
        (row.origin, origin),
        (row.region_code, region_code),
        (row.org_code, org_code),
        (row.profile_code, profile_code),
        (row.signal_id, signal_id),
    ):
        if value is not None:
            query = query.where(column == value)
    if with_alternatives is True:
        query = query.where(row.alternative_count > 0)
    elif with_alternatives is False:
        query = query.where(row.alternative_count == 0)
    return query.order_by(row.origin.desc(), row.signal_id, row.budget)


def alternative_sets(
    session: Session,
    snapshot_id: int,
    *,
    origin: dt.date | None = None,
    region_code: str | None = None,
    org_code: str | None = None,
    profile_code: str | None = None,
    signal_id: str | None = None,
    with_alternatives: bool | None = None,
    limit: int,
    offset: int,
) -> tuple[list[ReviewAlternativeSet], int]:
    query = _set_query(
        snapshot_id,
        origin=origin,
        region_code=region_code,
        org_code=org_code,
        profile_code=profile_code,
        signal_id=signal_id,
        with_alternatives=with_alternatives,
    )
    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    return list(session.scalars(query.limit(limit).offset(offset)).all()), total


def alternative_set(session: Session, snapshot_id: int, set_id: str) -> ReviewAlternativeSet | None:
    return session.scalar(
        select(ReviewAlternativeSet).where(
            ReviewAlternativeSet.snapshot_id == snapshot_id, ReviewAlternativeSet.set_id == set_id
        )
    )


def alternatives(session: Session, snapshot_id: int, set_ids: list[str]) -> list[ReviewAlternative]:
    if not set_ids:
        return []
    row = ReviewAlternative
    return list(
        session.scalars(
            select(row)
            .where(row.snapshot_id == snapshot_id, row.set_id.in_(set_ids))
            .order_by(row.set_id, row.position)
        ).all()
    )


def baseline_mismatch_count(
    session: Session, snapshot_id: int, scenario_id: str, operational_snapshot_id: int, tolerance: float
) -> int:
    """Identity-scenario cells must reproduce the published operational central forecasts exactly."""
    cell = ReviewScenarioCell
    forecast = OperationalForecast
    joined = (
        select(func.count())
        .select_from(cell)
        .outerjoin(
            forecast,
            (forecast.snapshot_id == operational_snapshot_id)
            & (forecast.series_id == cell.series_id)
            & (forecast.target == cell.target)
            & (forecast.origin == cell.origin)
            & (forecast.target_date == cell.target_date),
        )
        .where(
            cell.snapshot_id == snapshot_id,
            cell.scenario_id == scenario_id,
            (forecast.id.is_(None))
            | (func.abs(forecast.central_value - cell.baseline_central) > tolerance)
            | (func.abs(cell.scenario_central - cell.baseline_central) > tolerance),
        )
    )
    return session.scalar(joined) or 0


def operational_snapshot_by_identity(session: Session, identity: str) -> OperationalIntelligenceSnapshot | None:
    return session.scalar(
        select(OperationalIntelligenceSnapshot).where(
            OperationalIntelligenceSnapshot.publication_identity_sha256 == identity
        )
    )
