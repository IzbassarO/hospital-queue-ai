from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class BaselineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trailing_mean_days: int = Field(ge=1)
    trailing_median_days: int = Field(ge=1)
    recent_seasonal_periods: int = Field(ge=1)


class SupportConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_history_days: int = Field(ge=2)
    hospital_min_mean_registrations: float = Field(ge=0)
    region_parents_direct: bool
    national_from_region_aggregation: bool
    sparse_zero_rate: float = Field(ge=0, le=1)
    zero_heavy_zero_rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered_sparsity(self) -> SupportConfig:
        if self.zero_heavy_zero_rate < self.sparse_zero_rate:
            raise ValueError("zero-heavy threshold must be at least the sparse threshold")
        return self


class ChallengerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_config: str


class FlowForecastConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    seed: int
    horizon: int = Field(ge=1)
    validation_origins: list[dt.date] = Field(min_length=2)
    final_test_origin: dt.date
    extrapolation_report_ratio_threshold: float = Field(gt=1)
    extrapolation_examples: int = Field(ge=1)
    baselines: BaselineConfig
    support: SupportConfig
    challenger: ChallengerConfig
    automatic_promotion: bool
    identity_sha256: str = ""

    @model_validator(mode="after")
    def validate_protocol(self) -> FlowForecastConfig:
        if self.validation_origins != sorted(set(self.validation_origins)):
            raise ValueError("validation origins must be unique and sorted")
        validation_end = self.validation_origins[-1] + dt.timedelta(days=self.horizon)
        test_start = self.final_test_origin + dt.timedelta(days=1)
        if validation_end >= test_start:
            raise ValueError("validation targets must end before the untouched final test starts")
        if self.automatic_promotion:
            raise ValueError("the evidence workflow cannot enable automatic promotion")
        return self


def load_flow_config(path: Path) -> FlowForecastConfig:
    raw = path.read_bytes()
    config = FlowForecastConfig(**yaml.safe_load(raw))
    return config.model_copy(update={"identity_sha256": hashlib.sha256(raw).hexdigest()})
