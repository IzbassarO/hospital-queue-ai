"""ml/configs/serving.yaml, validated, plus the date windows derived from it."""

import datetime as dt
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class LoadIndexWeights(BaseModel):
    backlog_rank: float = Field(ge=0)
    refusal_rate: float = Field(ge=0)
    queue_trend: float = Field(ge=0)


class LoadIndexConfig(BaseModel):
    weights: LoadIndexWeights
    refusal_rate_cap: float = Field(gt=0)
    queue_trend_cap_pct: float = Field(gt=0)


class StatusThresholds(BaseModel):
    high: float
    elevated: float


class AlertsConfig(BaseModel):
    load_index_min: float
    queue_trend_min_pct: float
    queue_trend_min_queue_now: int = Field(ge=0)


class RecommendationsConfig(BaseModel):
    region_top_fraction: float = Field(gt=0, le=1)
    min_wait_delta_days: float = Field(ge=0)
    max_alternatives: int = Field(ge=1)
    min_registrations_28d: int = Field(ge=0)


class DataSource(BaseModel):
    publisher: str
    description: str
    period: str
    datasets: list[str]
    caveats: list[str] = []


class ServingConfig(BaseModel):
    as_of_date: dt.date
    window_days: int = Field(ge=1)
    min_registrations_28d: int = Field(ge=0)
    backlog_min_daily_throughput: float = Field(gt=0)
    trend_weeks: int = Field(ge=2)
    high_risk_threshold: float = Field(gt=0, lt=1)
    load_index: LoadIndexConfig
    status_thresholds: StatusThresholds
    alerts: AlertsConfig
    recommendations: RecommendationsConfig
    series_start: dt.date
    forecast_horizon: int = Field(ge=1)
    data_source: DataSource

    @model_validator(mode="after")
    def _check(self) -> "ServingConfig":
        if self.status_thresholds.elevated > self.status_thresholds.high:
            raise ValueError("status_thresholds.elevated must not exceed status_thresholds.high")
        if self.series_start > self.as_of_date:
            raise ValueError("series_start must not be after as_of_date")
        return self

    # ---- derived windows (all inclusive)
    @property
    def window_start(self) -> dt.date:
        return self.as_of_date - dt.timedelta(days=self.window_days - 1)

    @property
    def trend_end(self) -> dt.date:
        """Sunday of the last full Monday–Sunday week ending on or before as_of_date."""
        return self.as_of_date - dt.timedelta(days=self.as_of_date.isoweekday() % 7)

    @property
    def trend_start(self) -> dt.date:
        return self.trend_end - dt.timedelta(days=7 * self.trend_weeks - 1)


def load_serving_config(configs_dir: Path) -> ServingConfig:
    return ServingConfig(**yaml.safe_load((configs_dir / "serving.yaml").read_text(encoding="utf-8")))
