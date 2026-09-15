"""Overview, region, hospital-profile status responses."""
import datetime as dt

from pydantic import BaseModel, Field

from app.schemas.common import StatusMetrics


class AreaKpis(BaseModel):
    """Totals over all profiles for the country or one region."""

    code: str = Field(description="region code, or 'KZ' for the whole country")
    name: str
    level: str = Field(description="national | region")
    queue_now: int
    registrations_28d: int
    hospitalizations_28d: int
    refusals_28d: int
    refusal_rate_28d: float | None
    median_wait_28d: float | None
    n_waits_28d: int
    forecast_registrations_14d: float | None
    forecast_hospitalizations_14d: float | None
    high_risk_share: float | None
    n_hospitals: int
    n_hospital_profiles: int
    n_hospital_profiles_ranked: int = Field(description="hospital × profile rows with a load_index")
    load_index_max: float | None = Field(description="highest hospital × profile load_index")
    n_hospitals_high_load: int = Field(description="hospitals with at least one profile at load_index >= 70")
    n_hospital_profiles_high_load: int


class Thresholds(BaseModel):
    load_index_high: float
    load_index_elevated: float
    min_registrations_28d: int


class OverviewResponse(BaseModel):
    as_of_date: dt.date
    built_at: dt.datetime
    thresholds: Thresholds
    national: AreaKpis
    regions: list[AreaKpis]


class RegionProfileStatus(StatusMetrics):
    region_code: str
    region_name: str
    profile_code: str
    profile_name: str
    n_hospitals: int
    n_hospitals_high_load: int
    load_index_max_hospital: float | None


class RegionDetailResponse(BaseModel):
    region: AreaKpis
    profiles: list[RegionProfileStatus] = Field(description="all profiles of the region, highest load_index first")


class HospitalProfileStatus(StatusMetrics):
    region_code: str
    region_name: str
    org_code: str
    org_name: str
    profile_code: str
    profile_name: str
    forecast_method: str | None = Field(description="model | region_share_fallback")
    region_rank: int | None = Field(description="rank of load_index among the region's hospital × profile rows")
    region_n_ranked: int
    in_region_top: bool = Field(description="load_index in the top 20% of the region (recommendation trigger)")


class DailyPoint(BaseModel):
    date: dt.date
    registrations: int
    hospitalizations: int
    refusals: int
    queue: int


class ForecastPoint(BaseModel):
    date: dt.date
    horizon: int
    registrations: float
    hospitalizations: float


class Forecast(BaseModel):
    origin_date: dt.date | None
    model_version: str | None
    method: str | None
    points: list[ForecastPoint]
    note: str


class ExplanationFactor(BaseModel):
    feature: str
    label: str
    mean_abs_effect: float = Field(description="mean |effect| over the hospital × profile's test referrals "
                                               "(referrals where the factor is not in the top 5 count as 0)")
    mean_effect: float
    unit: str = Field(description="дн. (wait time) | п.п. (refusal risk)")
    direction: str = Field(description="up | down: sign of mean_effect")
    share_in_top5: float = Field(description="share of referrals where the factor is among the top 5")
    most_common_value: str | None


class ExplanationSummary(BaseModel):
    n_referrals: int
    wait_time: list[ExplanationFactor]
    refusal_risk: list[ExplanationFactor]


class HospitalProfileCard(BaseModel):
    status: HospitalProfileStatus
    series: list[DailyPoint]
    forecast: Forecast
    explanation_factors: ExplanationSummary
