"""Explicit temporal evaluation contracts for current and future model comparisons."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

from hqai_ml.models.config import ModelConfig


@dataclass(frozen=True)
class TemporalProtocol:
    train_start: dt.date
    train_end: dt.date
    validation_start: dt.date | None
    validation_end: dt.date | None
    test_start: dt.date
    test_end: dt.date
    forecast_origin: dt.date | None
    origin_semantics: str
    prediction_horizon_days: int | None
    backtest_origins: tuple[dt.date, ...]
    label_availability_rule: str
    feature_availability_cutoff: str
    leakage_exclusions: tuple[str, ...]
    warm_up_period: tuple[dt.date, dt.date] | None
    warm_up_note: str

    def validate(self) -> None:
        if self.train_start > self.train_end:
            raise ValueError("train_start must not be after train_end")
        if self.test_start > self.test_end:
            raise ValueError("test_start must not be after test_end")
        if self.train_end >= self.test_start:
            raise ValueError("training must end before the test period begins")
        if (self.validation_start is None) != (self.validation_end is None):
            raise ValueError("validation_start and validation_end must be set together")
        if self.validation_start is not None:
            assert self.validation_end is not None
            if not (self.train_start <= self.validation_start <= self.validation_end <= self.train_end):
                raise ValueError("validation must be a temporally ordered subset of the training period")
        if self.origin_semantics not in {"last_observed_day", "not_applicable"}:
            raise ValueError("origin_semantics must be last_observed_day or not_applicable")
        if self.backtest_origins and self.origin_semantics != "last_observed_day":
            raise ValueError("backtest origins must use last_observed_day semantics")
        if any(origin < self.train_end for origin in self.backtest_origins):
            raise ValueError("every backtest origin must be on or after the training end")
        if any(
            origin + dt.timedelta(days=1) < self.test_start or origin > self.test_end
            for origin in self.backtest_origins
        ):
            raise ValueError("every backtest origin must immediately precede or be inside the test period")
        if tuple(sorted(set(self.backtest_origins))) != self.backtest_origins:
            raise ValueError("backtest origins must be unique and ordered")
        if self.forecast_origin is not None:
            if self.origin_semantics != "last_observed_day":
                raise ValueError("forecast origin must use last_observed_day semantics")
            if self.forecast_origin < self.train_end:
                raise ValueError("forecast origin must not precede the training end")
            if self.forecast_origin > self.test_end:
                raise ValueError("forecast origin must not exceed the declared available period")
        if self.prediction_horizon_days is not None and self.prediction_horizon_days < 1:
            raise ValueError("prediction horizon must be positive")
        if self.backtest_origins and self.prediction_horizon_days is None:
            raise ValueError("backtest origins require a prediction horizon")
        if self.prediction_horizon_days is not None and any(
            origin + dt.timedelta(days=self.prediction_horizon_days) > self.test_end for origin in self.backtest_origins
        ):
            raise ValueError("a backtest horizon extends past the test period")

    def to_dict(self) -> dict:
        self.validate()
        return asdict(self)


def referral_protocol(cfg: ModelConfig) -> TemporalProtocol:
    split = cfg.split
    validation_start = split.train_end - dt.timedelta(days=cfg.early_stopping.holdout_days - 1)
    protocol = TemporalProtocol(
        train_start=split.train_start,
        train_end=split.train_end,
        validation_start=validation_start,
        validation_end=split.train_end,
        test_start=split.test_start,
        test_end=split.test_end,
        forecast_origin=None,
        origin_semantics="not_applicable",
        prediction_horizon_days=None,
        backtest_origins=(),
        label_availability_rule=(
            "wait_time: hospitalized non-same-day referrals with observed wait_days; refusal_risk: referrals with "
            "resolved hospitalized/refused outcomes. Production censoring is not yet modelled."
        ),
        feature_availability_cutoff=(
            "features are available at the start of registration day d; aggregates end at d-1 and outcome-derived "
            "statistics require resolution strictly before d"
        ),
        leakage_exclusions=("planned_dt", "planned_lag_days"),
        warm_up_period=None,
        warm_up_note="No warm-up rows are excluded; day_of_window represents early-window feature maturity.",
    )
    protocol.validate()
    return protocol


def forecast_protocol(cfg: ModelConfig) -> TemporalProtocol:
    split, forecast = cfg.split, cfg.load_forecast
    protocol = TemporalProtocol(
        train_start=split.train_start,
        train_end=split.train_end,
        validation_start=None,
        validation_end=None,
        test_start=split.test_start,
        test_end=split.test_end,
        forecast_origin=forecast.forecast_origin,
        origin_semantics="last_observed_day",
        prediction_horizon_days=forecast.horizon,
        backtest_origins=tuple(forecast.backtest_origins),
        label_availability_rule=("origin is the last observed day; horizons 1..h predict origin+1 through origin+h"),
        feature_availability_cutoff=(
            "for origin t, every lag, rolling statistic, queue, and calendar feature uses t or earlier"
        ),
        leakage_exclusions=("future target values", "future queue values", "post-origin aggregates"),
        warm_up_period=None,
        warm_up_note="No warm-up rows are excluded; unavailable early lags remain missing model inputs.",
    )
    protocol.validate()
    return protocol


def protocols_for(models: list[str], cfg: ModelConfig) -> dict[str, dict]:
    return {
        name: (forecast_protocol(cfg) if name == "load_forecast" else referral_protocol(cfg)).to_dict()
        for name in models
    }
