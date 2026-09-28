from __future__ import annotations

from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import pandas as pd

from hqai_ml.origin_journey.config import OriginJourneyConfig
from hqai_ml.origin_journey.encoding import CATEGORICAL_FEATURES, FeatureEncoder
from hqai_ml.origin_journey.time_grid import build_time_grid

EVENT_CODE = {"censored": 0, "hospitalized": 1, "refused": 2}


def _edges(config: OriginJourneyConfig) -> tuple[int, ...]:
    intervals = build_time_grid(config)
    return tuple(interval.start_day for interval in intervals) + (intervals[-1].end_day,)


def expand_person_period(
    frame: pd.DataFrame,
    encoder: FeatureEncoder,
    edges: tuple[int, ...],
) -> tuple[pd.DataFrame, np.ndarray]:
    """Expand fully observed risk intervals without leaking a later event into earlier bins."""
    base = encoder.transform(frame)
    duration = frame["observed_duration_days"].to_numpy(float)
    events = frame["event_type_at_origin"].map(EVENT_CODE).to_numpy(np.int8)
    parts: list[pd.DataFrame] = []
    labels: list[np.ndarray] = []
    categories = [str(index) for index in range(len(edges) - 1)]
    for interval, (start, end) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        completed = duration >= end
        event_here = (events != 0) & (duration > start) & (duration <= end)
        usable = completed | event_here
        if not usable.any():
            continue
        part = base.loc[usable].copy()
        part["time_interval"] = pd.Categorical(
            np.full(int(usable.sum()), str(interval)),
            categories=categories,
        )
        y = np.zeros(int(usable.sum()), dtype=np.int8)
        y[event_here[usable]] = events[event_here]
        parts.append(part)
        labels.append(y)
    if not parts:
        raise ValueError("no fully observed person-period rows were produced")
    return pd.concat(parts, ignore_index=True), np.concatenate(labels)


@dataclass(frozen=True)
class CompetingHazardModel:
    booster: lgb.Booster
    encoder: FeatureEncoder
    edges: tuple[int, ...]
    iterations: int

    def interval_probabilities(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        base = self.encoder.transform(frame)
        hospitalized = np.empty((len(frame), len(self.edges) - 1), dtype=np.float64)
        refused = np.empty_like(hospitalized)
        categories = [str(index) for index in range(len(self.edges) - 1)]
        for interval in range(len(self.edges) - 1):
            matrix = base.copy()
            matrix["time_interval"] = pd.Categorical(
                np.full(len(frame), str(interval)),
                categories=categories,
            )
            prediction = self.booster.predict(matrix, num_iteration=self.iterations)
            hospitalized[:, interval] = prediction[:, 1]
            refused[:, interval] = prediction[:, 2]
        return hospitalized, refused

    def _state(
        self,
        days: np.ndarray,
        hospitalized_hazard: np.ndarray,
        refused_hazard: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        days = np.asarray(days, dtype=float)
        survival = np.ones(len(days), dtype=float)
        hospitalized_cif = np.zeros(len(days), dtype=float)
        refused_cif = np.zeros(len(days), dtype=float)
        for interval, (start, end) in enumerate(zip(self.edges[:-1], self.edges[1:], strict=True)):
            fraction = np.clip((days - start) / (end - start), 0, 1)
            h_h = hospitalized_hazard[:, interval]
            h_r = refused_hazard[:, interval]
            total = np.clip(h_h + h_r, 0, 1 - 1e-12)
            interval_survival = np.power(1 - total, fraction)
            event_fraction = 1 - interval_survival
            hospitalized_share = np.divide(h_h, total, out=np.zeros_like(h_h), where=total > 0)
            refused_share = np.divide(h_r, total, out=np.zeros_like(h_r), where=total > 0)
            hospitalized_cif += survival * event_fraction * hospitalized_share
            refused_cif += survival * event_fraction * refused_share
            survival *= interval_survival
        return hospitalized_cif, refused_cif, survival

    def probabilities(self, scoring: pd.DataFrame, horizons: tuple[int, ...]) -> dict[int, dict[str, np.ndarray]]:
        h_h, h_r = self.interval_probabilities(scoring)
        waited = scoring["days_waited_at_origin"].to_numpy(float)
        start_h, start_r, start_s = self._state(waited, h_h, h_r)
        denominator = np.clip(start_s, 1e-12, None)
        output = {}
        for horizon in horizons:
            end_h, end_r, end_s = self._state(waited + horizon, h_h, h_r)
            hospitalized = np.clip((end_h - start_h) / denominator, 0, 1)
            refused = np.clip((end_r - start_r) / denominator, 0, 1)
            unresolved = np.clip(end_s / denominator, 0, 1)
            normalizer = np.clip(hospitalized + refused + unresolved, 1e-12, None)
            output[horizon] = {
                "hospitalized": hospitalized / normalizer,
                "refused": refused / normalizer,
                "unresolved": unresolved / normalizer,
            }
        return output

    def admission_intervals(self, scoring: pd.DataFrame, coverage: float) -> pd.DataFrame:
        h_h, h_r = self.interval_probabilities(scoring)
        waited = scoring["days_waited_at_origin"].to_numpy(float)
        start_h = self._state(waited, h_h, h_r)[0]
        maximum = float(self.edges[-1])
        max_h = self._state(np.full(len(scoring), maximum), h_h, h_r)[0]
        future_mass = np.maximum(0.0, max_h - start_h)
        lower_q = (1 - coverage) / 2
        upper_q = 1 - lower_q
        results = []
        for quantile in (lower_q, upper_q):
            target = start_h + quantile * future_mass
            low = np.ceil(waited).astype(int)
            high = np.full(len(scoring), int(maximum), dtype=int)
            for _ in range(10):
                active = low < high
                if not active.any():
                    break
                middle = (low + high) // 2
                value = self._state(middle.astype(float), h_h, h_r)[0]
                reached = value >= target
                high = np.where(active & reached, middle, high)
                low = np.where(active & ~reached, middle + 1, low)
            delta = np.maximum(0.0, low.astype(float) - waited)
            delta[future_mass <= 1e-12] = np.nan
            results.append(delta)
        lower, upper = results
        return pd.DataFrame(
            {
                "admission_interval_lower_days": lower,
                "admission_interval_upper_days": upper,
                "admission_interval_width_days": upper - lower,
                "future_admission_mass_through_grid": future_mass,
            }
        )


def _parameters(config: OriginJourneyConfig) -> dict:
    policy = config.training.competing_hazard
    return {
        "objective": "multiclass",
        "metric": "multi_logloss",
        "num_class": 3,
        "num_leaves": policy.num_leaves,
        "learning_rate": policy.learning_rate,
        "min_data_in_leaf": policy.min_data_in_leaf,
        "seed": config.seed,
        "feature_fraction_seed": config.seed,
        "bagging_seed": config.seed,
        "data_random_seed": config.seed,
        "num_threads": config.training.threads,
        "verbosity": -1,
        "deterministic": True,
        "force_row_wise": True,
    }


def fit_competing_hazard(training: pd.DataFrame, config: OriginJourneyConfig) -> tuple[CompetingHazardModel, dict]:
    eligible = training.loc[training["label_eligible"]].copy()
    validation_start = config.training.validation_registration_start
    validation = pd.to_datetime(eligible["registration_date"]).dt.date >= validation_start
    fit_frame = eligible.loc[~validation]
    validation_frame = eligible.loc[validation]
    if fit_frame.empty or validation_frame.empty:
        raise ValueError("hazard early stopping requires non-empty temporal fit and validation rows")
    edges = _edges(config)
    encoder = FeatureEncoder.fit(fit_frame)
    X_fit, y_fit = expand_person_period(fit_frame, encoder, edges)
    X_validation, y_validation = expand_person_period(validation_frame, encoder, edges)
    categorical = [*CATEGORICAL_FEATURES, "time_interval"]
    fit_dataset = lgb.Dataset(X_fit, y_fit, categorical_feature=categorical, free_raw_data=False)
    validation_dataset = lgb.Dataset(
        X_validation,
        y_validation,
        categorical_feature=categorical,
        reference=fit_dataset,
        free_raw_data=False,
    )
    parameters = _parameters(config)
    probe = lgb.train(
        parameters,
        fit_dataset,
        num_boost_round=config.training.competing_hazard.max_rounds,
        valid_sets=[validation_dataset],
        callbacks=[lgb.early_stopping(config.training.early_stopping_rounds, verbose=False)],
    )
    iterations = max(1, int(probe.best_iteration))
    fit_expanded_rows = len(X_fit)
    validation_expanded_rows = len(X_validation)
    del X_fit, X_validation, y_fit, y_validation, fit_dataset, validation_dataset, probe

    final_encoder = FeatureEncoder.fit(eligible)
    X_final, y_final = expand_person_period(eligible, final_encoder, edges)
    final_expanded_rows = len(X_final)
    final = lgb.train(
        parameters,
        lgb.Dataset(X_final, y_final, categorical_feature=categorical),
        num_boost_round=iterations,
    )
    metadata = {
        "fit_rows": int((~validation).sum()),
        "validation_rows": int(validation.sum()),
        "final_rows": int(len(eligible)),
        "fit_person_period_rows": fit_expanded_rows,
        "validation_person_period_rows": validation_expanded_rows,
        "final_person_period_rows": final_expanded_rows,
        "selected_iterations": iterations,
        "parameters": parameters,
        "time_edges": list(edges),
    }
    return CompetingHazardModel(final, final_encoder, edges, iterations), metadata
