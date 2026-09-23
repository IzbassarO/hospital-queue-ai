"""Health, models, dictionaries."""

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="ok | degraded")
    database: str = Field(description="ok | unavailable")
    marts_as_of_date: dt.date | None
    marts_built_at: dt.datetime | None


class ModelInfo(BaseModel):
    model_name: str
    title: str
    intended_use: str | None
    limitations: list[str] = Field(description="model card, ml/configs/model_cards.yaml via the artifact's card.json")
    display_names: dict[str, str] = Field(
        description="labels for metric keys, baseline / method names, series levels and targets in headline/baselines"
    )
    version: str
    trained_at: dt.datetime
    train_window: dict[str, Any]
    population: dict[str, Any] | None
    headline: list[dict[str, Any]] = Field(
        description="the model's own metrics (per target × series level for load_forecast)"
    )
    baselines: list[dict[str, Any]] = Field(description="naive baselines evaluated on the same rows")
    beats_baselines: bool | None = Field(description="load_forecast: beats seasonal naive everywhere; NULL for A/B")


class DictionaryItem(BaseModel):
    code: str
    name: str


class ProfileItem(DictionaryItem):
    is_day_hospital: bool


class OrganizationItem(BaseModel):
    code: str
    name: str
    region_code: str | None


class DictionariesResponse(BaseModel):
    national_code: str
    regions: list[DictionaryItem]
    profiles: list[ProfileItem]
    organizations: list[OrganizationItem] = Field(
        default_factory=list, description="medical organizations (hospital codes with names) for display"
    )


class LoadIndexWeights(BaseModel):
    backlog_rank: float
    refusal_rate: float
    queue_trend: float


class LoadIndexConfig(BaseModel):
    weights: LoadIndexWeights
    refusal_rate_cap: float = Field(description="refusal_score = min(refusal_rate_28d / cap, 1)")
    queue_trend_cap_pct: float = Field(description="trend_score = min(max(queue_trend_4w, 0) / cap, 1)")


class StatusThresholdsConfig(BaseModel):
    high: float
    elevated: float


class AlertRuleConfig(BaseModel):
    load_index_min: float
    queue_trend_min_pct: float
    queue_trend_min_queue_now: int


class RecommendationRuleConfig(BaseModel):
    region_top_fraction: float
    min_wait_delta_days: float
    max_alternatives: int
    min_registrations_28d: int


class DataSourceInfo(BaseModel):
    publisher: str
    description: str
    period: str
    datasets: list[str]
    caveats: list[str]


class ConfigResponse(BaseModel):
    """Parameters the marts were built with (ml/configs/serving.yaml, copied at `make marts`)."""

    as_of_date: dt.date
    built_at: dt.datetime
    window_days: int
    window_start: dt.date
    trend_start: dt.date
    trend_end: dt.date
    test_start: dt.date
    test_end: dt.date
    series_start: dt.date
    forecast_horizon: int
    min_registrations_28d: int
    backlog_min_daily_throughput: float
    high_risk_threshold: float
    queue_trend_national_median_4w: float | None
    load_index: LoadIndexConfig
    status_thresholds: StatusThresholdsConfig
    alerts: AlertRuleConfig
    recommendations: RecommendationRuleConfig
    data_source: DataSourceInfo


class MeResponse(BaseModel):
    label: str
    role: str = Field(description="viewer | specialist | admin")
    role_label: str = Field(description="Russian name of the role")
    permissions: list[str]
