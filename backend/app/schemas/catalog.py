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


class DictionariesResponse(BaseModel):
    national_code: str
    regions: list[DictionaryItem]
    profiles: list[ProfileItem]
