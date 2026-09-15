"""Shared response pieces: pagination, load-index status block."""
import datetime as dt
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

Status = Literal["high", "elevated", "normal", "insufficient_data"]

STATUS_LABELS: dict[str, str] = {
    "high": "Высокая нагрузка",
    "elevated": "Повышенная нагрузка",
    "normal": "Нормальная нагрузка",
    "insufficient_data": "Недостаточно данных",
}


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="rows matching the filters, before limit/offset")
    limit: int
    offset: int


class LoadIndexComponents(BaseModel):
    """Scores behind load_index, each in [0, 1] (NULL when the component is undefined)."""

    backlog_score: float | None = Field(description="mid-rank percentile of backlog within the profile nationally")
    refusal_score: float | None = Field(description="refusal_rate_28d / refusal_rate_cap, clipped to [0, 1]")
    trend_score: float | None = Field(description="max(queue_trend_4w, 0) / queue_trend_cap_pct, clipped to [0, 1]")


class StatusMetrics(BaseModel):
    """Metrics of one hospital × profile or region × profile as of the last known day."""

    as_of_date: dt.date
    queue_now: int = Field(description="referrals waiting at the end of as_of_date")
    registrations_28d: int
    hospitalizations_28d: int
    refusals_28d: int
    refusal_rate_28d: float | None = Field(description="refusals / (hospitalizations + refusals) in the window")
    n_waits_28d: int = Field(description="non-same-day hospitalizations behind median_wait_28d")
    median_wait_28d: float | None = Field(description="days, non-same-day hospitalizations in the window")
    daily_throughput_28d: float = Field(description="hospitalizations_28d / 28")
    backlog_days: float | None = Field(description="queue_now / daily throughput; NULL below 0.5 hospitalizations/day")
    forecast_registrations_14d: float | None
    forecast_hospitalizations_14d: float | None
    n_test_referrals: int = Field(description="referrals of the test period scored by model B")
    high_risk_share: float | None = Field(description="share of test-period referrals with refusal probability >= 0.25")
    queue_trend_4w: float | None = Field(description="% of the mean weekly queue per week, last 4 full weeks")
    has_sufficient_data: bool = Field(description="registrations_28d >= 10; otherwise no load_index")
    load_index: float | None = Field(description="0–100, see docs/api.md")
    status: Status
    status_label: str
    components: LoadIndexComponents


class Message(BaseModel):
    detail: str
