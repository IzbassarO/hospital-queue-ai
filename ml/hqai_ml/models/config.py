import datetime as dt

import yaml
from pydantic import BaseModel

from hqai_ml.ingest.config import IngestSettings


class Split(BaseModel):
    train_start: dt.date
    train_end: dt.date
    test_start: dt.date
    test_end: dt.date


class EarlyStopping(BaseModel):
    holdout_days: int
    max_rounds: int
    patience: int


class WaitTimeConfig(BaseModel):
    within_days: int
    top_profiles: int


class RefusalRiskConfig(BaseModel):
    top_fraction: float
    calibration_bins: int


class LoadForecastConfig(BaseModel):
    horizon: int
    lags: list[int]
    rolling: list[int]
    backtest_origins: list[dt.date]
    forecast_origin: dt.date
    min_series_mean: float
    objective: str
    rounds: int
    top_hospitals: int
    holidays: list[dt.date]


class ExplainConfig(BaseModel):
    top_k: int
    shap_sample: int


class ModelConfig(BaseModel):
    split: Split
    early_stopping: EarlyStopping
    lightgbm: dict
    wait_time: WaitTimeConfig
    refusal_risk: RefusalRiskConfig
    load_forecast: LoadForecastConfig
    explain: ExplainConfig


def load_model_config(settings: IngestSettings | None = None) -> ModelConfig:
    settings = settings or IngestSettings()
    return ModelConfig(**yaml.safe_load((settings.configs_dir / "models.yaml").read_text(encoding="utf-8")))
