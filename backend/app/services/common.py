"""Shared service helpers: errors, the serving parameters the marts were built with, row → schema."""

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import (
    DimOrganization,
    DimProfile,
    DimRegion,
    MartAreaStatus,
    MartBuildInfo,
    MartHospitalProfileStatus,
    MartRegionProfileStatus,
)
from app.schemas.common import STATUS_LABELS, LoadIndexComponents
from app.schemas.status import AreaKpis, HospitalProfileStatus, RegionProfileStatus


class NotFoundError(Exception):
    """Unknown code; mapped to HTTP 404."""


class ValidationError(Exception):
    """Semantically invalid request; mapped to HTTP 422."""


class ConflictError(Exception):
    """The request conflicts with stored state (e.g. a reused idempotency key); mapped to HTTP 409."""


class MartsNotBuiltError(Exception):
    """mart_build_info is empty; mapped to HTTP 503."""


@dataclass(frozen=True)
class BuildInfo:
    as_of_date: dt.date
    built_at: dt.datetime
    config: dict[str, Any]

    @property
    def national_code(self) -> str:
        return self.config["derived"]["national_code"]

    def date(self, key: str) -> dt.date:
        """A date parameter of the build: top-level key (series_start) or a derived one (test_start)."""
        value = self.config.get(key, self.config["derived"].get(key))
        return dt.date.fromisoformat(str(value))


def build_info(session: Session) -> BuildInfo:
    row = session.get(MartBuildInfo, 1)
    if row is None:
        raise MartsNotBuiltError("serving marts are not built yet: run `make marts`")
    return BuildInfo(as_of_date=row.as_of_date, built_at=row.built_at, config=row.config)


def rnd(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


_METRIC_DIGITS = {
    "refusal_rate_28d": 4,
    "median_wait_28d": 1,
    "daily_throughput_28d": 2,
    "backlog_days": 1,
    "forecast_registrations_14d": 1,
    "forecast_hospitalizations_14d": 1,
    "high_risk_share": 4,
    "queue_trend_raw_4w": 1,
    "queue_trend_4w": 1,
    "load_index": 1,
}
_INT_METRICS = (
    "queue_now",
    "registrations_28d",
    "hospitalizations_28d",
    "refusals_28d",
    "n_waits_28d",
    "n_test_referrals",
)


def _metrics(row: MartHospitalProfileStatus | MartRegionProfileStatus) -> dict[str, Any]:
    out: dict[str, Any] = {k: getattr(row, k) for k in _INT_METRICS}
    out.update({k: rnd(getattr(row, k), d) for k, d in _METRIC_DIGITS.items()})
    out.update(
        as_of_date=row.as_of_date,
        has_sufficient_data=row.has_sufficient_data,
        status=row.status,
        status_label=STATUS_LABELS[row.status],
        components=LoadIndexComponents(
            backlog_score=rnd(row.backlog_score, 4),
            refusal_score=rnd(row.refusal_score, 4),
            trend_score=rnd(row.trend_score, 4),
        ),
    )
    return out


def hospital_status(row: MartHospitalProfileStatus) -> HospitalProfileStatus:
    return HospitalProfileStatus(
        **_metrics(row),
        region_code=row.region_code,
        region_name=row.region_name,
        org_code=row.org_code,
        org_name=row.org_name,
        profile_code=row.profile_code,
        profile_name=row.profile_name,
        forecast_method=row.forecast_method,
        region_rank=row.region_rank,
        region_n_ranked=row.region_n_ranked,
        in_region_top=row.in_region_top,
    )


def region_status(row: MartRegionProfileStatus) -> RegionProfileStatus:
    return RegionProfileStatus(
        **_metrics(row),
        region_code=row.region_code,
        region_name=row.region_name,
        profile_code=row.profile_code,
        profile_name=row.profile_name,
        n_hospitals=row.n_hospitals,
        n_hospitals_high_load=row.n_hospitals_high_load,
        load_index_max_hospital=rnd(row.load_index_max_hospital, 1),
    )


def area_kpis(row: MartAreaStatus) -> AreaKpis:
    return AreaKpis(
        code=row.area_code,
        name=row.area_name,
        level=row.area_level,
        queue_now=row.queue_now,
        registrations_28d=row.registrations_28d,
        hospitalizations_28d=row.hospitalizations_28d,
        refusals_28d=row.refusals_28d,
        refusal_rate_28d=rnd(row.refusal_rate_28d, 4),
        median_wait_28d=rnd(row.median_wait_28d, 1),
        n_waits_28d=row.n_waits_28d,
        forecast_registrations_14d=rnd(row.forecast_registrations_14d, 1),
        forecast_hospitalizations_14d=rnd(row.forecast_hospitalizations_14d, 1),
        high_risk_share=rnd(row.high_risk_share, 4),
        n_hospitals=row.n_hospitals,
        n_hospital_profiles=row.n_hospital_profiles,
        n_hospital_profiles_ranked=row.n_hospital_profiles_ranked,
        load_index_max=rnd(row.load_index_max, 1),
        n_hospitals_high_load=row.n_hospitals_high_load,
        n_hospital_profiles_high_load=row.n_hospital_profiles_high_load,
        high_load_share=(
            rnd(row.n_hospital_profiles_high_load / row.n_hospital_profiles_ranked, 4)
            if row.n_hospital_profiles_ranked
            else None
        ),
    )


def hospital_row(session: Session, org_code: str, profile_code: str) -> MartHospitalProfileStatus:
    row = session.get(MartHospitalProfileStatus, (org_code, profile_code))
    if row is None:
        if session.get(DimOrganization, org_code) is None:
            raise NotFoundError(f"unknown hospital {org_code!r}")
        raise NotFoundError(f"hospital {org_code!r} has no referrals for profile {profile_code!r}")
    return row


def require_region(session: Session, region_code: str) -> DimRegion:
    region = session.get(DimRegion, region_code)
    if region is None:
        raise NotFoundError(f"unknown region {region_code!r}")
    return region


def require_profile(session: Session, profile_code: str) -> DimProfile:
    profile = session.get(DimProfile, profile_code)
    if profile is None:
        raise NotFoundError(f"unknown profile {profile_code!r}")
    return profile


def page_bounds(total: int, limit: int, offset: int) -> dict[str, int]:
    return {"total": total, "limit": limit, "offset": offset}


def load_index_order():
    """Highest load first; rows without an index last, larger queues first among equals."""
    m = MartHospitalProfileStatus
    return (m.load_index.desc().nulls_last(), m.queue_now.desc(), m.org_code, m.profile_code)
