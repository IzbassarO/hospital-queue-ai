from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.special import expit, ndtr, ndtri

from hqai_ml.origin_journey.config import OriginJourneyConfig
from hqai_ml.origin_journey.encoding import FeatureEncoder


def _bounds(frame: pd.DataFrame, minimum_duration: float) -> tuple[np.ndarray, np.ndarray]:
    lower = np.clip(frame["observed_duration_days"].to_numpy(float), minimum_duration, None)
    upper = lower.copy()
    admitted = frame["event_type_at_origin"].astype(str).to_numpy() == "hospitalized"
    upper[~admitted] = np.inf
    return lower, upper


def _matrix(frame: pd.DataFrame, encoder: FeatureEncoder, minimum_duration: float) -> xgb.DMatrix:
    matrix = xgb.DMatrix(encoder.transform(frame), enable_categorical=True)
    lower, upper = _bounds(frame, minimum_duration)
    matrix.set_float_info("label_lower_bound", lower)
    matrix.set_float_info("label_upper_bound", upper)
    return matrix


@dataclass(frozen=True)
class AFTModel:
    booster: xgb.Booster
    encoder: FeatureEncoder
    distribution: str
    scale: float
    iterations: int

    def predicted_time(self, frame: pd.DataFrame) -> np.ndarray:
        matrix = xgb.DMatrix(self.encoder.transform(frame), enable_categorical=True)
        return np.clip(self.booster.predict(matrix, iteration_range=(0, self.iterations)), 1e-9, None)

    def _cdf_from_time(self, predicted_time: np.ndarray, days: np.ndarray) -> np.ndarray:
        positive_days = np.clip(np.asarray(days, dtype=float), 1e-9, None)
        z = (np.log(positive_days) - np.log(predicted_time)) / self.scale
        if self.distribution == "normal":
            result = ndtr(z)
        elif self.distribution == "logistic":
            result = expit(z)
        else:
            result = 1 - np.exp(-np.exp(z))
        return np.where(np.asarray(days) <= 0, 0.0, np.clip(result, 0, 1))

    def probabilities(self, scoring: pd.DataFrame, horizons: tuple[int, ...]) -> dict[int, dict[str, np.ndarray]]:
        predicted_time = self.predicted_time(scoring)
        waited = scoring["days_waited_at_origin"].to_numpy(float)
        start = self._cdf_from_time(predicted_time, waited)
        survival = np.clip(1 - start, 1e-12, None)
        output = {}
        for horizon in horizons:
            end = self._cdf_from_time(predicted_time, waited + horizon)
            hospitalized = np.clip((end - start) / survival, 0, 1)
            output[horizon] = {
                "hospitalized": hospitalized,
                # AFT treats refusal as censoring and therefore emits no refusal probability.
                "refused": np.zeros(len(scoring), dtype=float),
                "unresolved": 1 - hospitalized,
            }
        return output

    def admission_intervals(self, scoring: pd.DataFrame, coverage: float) -> pd.DataFrame:
        predicted_time = self.predicted_time(scoring)
        waited = scoring["days_waited_at_origin"].to_numpy(float)
        start = self._cdf_from_time(predicted_time, waited)
        survival = np.clip(1 - start, 1e-12, None)
        lower_q = (1 - coverage) / 2
        upper_q = 1 - lower_q
        probabilities = [start + lower_q * survival, start + upper_q * survival]
        quantiles = []
        for probability in probabilities:
            clipped = np.clip(probability, 1e-12, 1 - 1e-12)
            if self.distribution == "normal":
                z = ndtri(clipped)
            elif self.distribution == "logistic":
                z = np.log(clipped / (1 - clipped))
            else:
                z = np.log(-np.log1p(-clipped))
            quantiles.append(np.maximum(0.0, predicted_time * np.exp(self.scale * z) - waited))
        lower, upper = quantiles
        return pd.DataFrame(
            {
                "admission_interval_lower_days": lower,
                "admission_interval_upper_days": upper,
                "admission_interval_width_days": upper - lower,
                "future_admission_mass_through_grid": np.ones(len(scoring), dtype=float),
            }
        )


def fit_aft(training: pd.DataFrame, config: OriginJourneyConfig) -> tuple[AFTModel, dict]:
    eligible = training.loc[training["label_eligible"]].copy()
    validation_start = config.training.validation_registration_start
    validation = pd.to_datetime(eligible["registration_date"]).dt.date >= validation_start
    if not validation.any() or validation.all():
        raise ValueError("AFT early stopping requires non-empty temporal fit and validation rows")
    fit_frame = eligible.loc[~validation]
    validation_frame = eligible.loc[validation]
    encoder = FeatureEncoder.fit(fit_frame)
    minimum = config.label_contract.same_day_min_duration_days
    dtrain = _matrix(fit_frame, encoder, minimum)
    dvalidation = _matrix(validation_frame, encoder, minimum)
    policy = config.training.aft
    parameters = {
        "objective": "survival:aft",
        "eval_metric": "aft-nloglik",
        "tree_method": "hist",
        "max_depth": policy.max_depth,
        "learning_rate": policy.learning_rate,
        "min_child_weight": policy.min_child_weight,
        "aft_loss_distribution": policy.distribution,
        "aft_loss_distribution_scale": policy.distribution_scale,
        "seed": config.seed,
        "nthread": config.training.threads,
    }
    probe = xgb.train(
        parameters,
        dtrain,
        num_boost_round=policy.max_rounds,
        evals=[(dvalidation, "validation")],
        early_stopping_rounds=config.training.early_stopping_rounds,
        verbose_eval=False,
    )
    iterations = int(probe.best_iteration) + 1
    final_encoder = FeatureEncoder.fit(eligible)
    final = xgb.train(
        parameters,
        _matrix(eligible, final_encoder, minimum),
        num_boost_round=iterations,
        verbose_eval=False,
    )
    metadata = {
        "fit_rows": int((~validation).sum()),
        "validation_rows": int(validation.sum()),
        "final_rows": int(len(eligible)),
        "selected_iterations": iterations,
        "validation_best_score": float(probe.best_score),
        "parameters": parameters,
    }
    return AFTModel(final, final_encoder, policy.distribution, policy.distribution_scale, iterations), metadata
