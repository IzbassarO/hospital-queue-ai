from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.special import expit

from hqai_ml.features.referral import CATEGORICAL, NUMERIC, REFUSAL_EXTRA
from hqai_ml.models.referral_model import ReferralModel
from hqai_ml.tournament.labels import EVENT_CENSORED, EVENT_HOSPITALIZED, EVENT_REFUSED, aft_bounds

NUMERIC_FEATURES = [feature for feature in NUMERIC if feature != "day_of_window"] + REFUSAL_EXTRA
FEATURES = CATEGORICAL + NUMERIC_FEATURES


@dataclass
class CategoricalFrameEncoder:
    """Train-fitted pandas categories for native XGBoost/LightGBM handling."""

    categories: dict[str, list[str]]

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> CategoricalFrameEncoder:
        return cls({column: sorted(frame[column].dropna().astype(str).unique().tolist()) for column in CATEGORICAL})

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        output = pd.DataFrame(index=frame.index)
        for feature in FEATURES:
            if feature in self.categories:
                values = frame[feature].astype("string")
                output[feature] = pd.Categorical(values, categories=self.categories[feature])
            else:
                output[feature] = pd.to_numeric(frame[feature], errors="coerce").astype("float32")
        return output


@dataclass
class FrequencyEncoder:
    """Train-only frequency encoding for linear probes; unknown categories map to zero."""

    frequencies: dict[str, dict[str, float]]
    medians: dict[str, float]

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> FrequencyEncoder:
        frequencies = {
            column: frame[column].astype("string").value_counts(normalize=True, dropna=True).to_dict()
            for column in CATEGORICAL
        }
        medians = {}
        for column in NUMERIC_FEATURES:
            value = pd.to_numeric(frame[column], errors="coerce").median()
            medians[column] = float(value) if pd.notna(value) else 0.0
        return cls(frequencies, medians)

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        columns = []
        for feature in FEATURES:
            if feature in self.frequencies:
                values = frame[feature].astype("string").map(self.frequencies[feature]).fillna(0.0)
            else:
                values = pd.to_numeric(frame[feature], errors="coerce").fillna(self.medians[feature])
            columns.append(values.to_numpy(dtype=np.float32))
        return np.column_stack(columns)


# Backwards-compatible import name for older local tests; no ordinal codes are produced.
MatrixEncoder = CategoricalFrameEncoder


def _aj_estimate(labels: pd.DataFrame, horizons: list[int]) -> dict[int, tuple[float, float, float]]:
    duration = labels["journey_duration_days"].to_numpy(float)
    event = labels["journey_event"].to_numpy(int)
    result = {}
    survival = 1.0
    cif_h = cif_r = 0.0
    event_mask = (event != EVENT_CENSORED) & (duration <= max(horizons))
    times, inverse = np.unique(duration[event_mask], return_inverse=True)
    event_values = event[event_mask]
    d_hospitalized = np.bincount(
        inverse, weights=(event_values == EVENT_HOSPITALIZED).astype(int), minlength=len(times)
    )
    d_refused = np.bincount(inverse, weights=(event_values == EVENT_REFUSED).astype(int), minlength=len(times))
    sorted_duration = np.sort(duration)
    risk_counts = len(duration) - np.searchsorted(sorted_duration, times, side="left")
    position = 0
    for horizon in horizons:
        while position < len(times) and times[position] <= horizon:
            risk = int(risk_counts[position])
            d_h = int(d_hospitalized[position])
            d_r = int(d_refused[position])
            if risk:
                cif_h += survival * d_h / risk
                cif_r += survival * d_r / risk
                survival *= 1 - (d_h + d_r) / risk
            position += 1
        result[horizon] = (cif_h, cif_r, survival)
    return result


def empirical_competing_probabilities(
    train: pd.DataFrame,
    target: pd.DataFrame,
    horizons: list[int],
    group_columns: list[str],
    min_support: int,
) -> dict[int, dict[str, np.ndarray]]:
    global_curve = _aj_estimate(train, horizons)
    curves = {}
    for key, group in train.groupby(group_columns, dropna=False):
        if len(group) >= min_support:
            curves[key if isinstance(key, tuple) else (key,)] = _aj_estimate(group, horizons)
    target_keys = [tuple(row) for row in target[group_columns].itertuples(index=False, name=None)]
    output = {}
    for horizon in horizons:
        values = [curves.get(key, global_curve)[horizon] for key in target_keys]
        output[horizon] = {
            "hospitalized": np.asarray([value[0] for value in values]),
            "refused": np.asarray([value[1] for value in values]),
            "unresolved": np.asarray([value[2] for value in values]),
        }
    return output


@dataclass
class AFTModel:
    booster: xgb.Booster
    encoder: CategoricalFrameEncoder
    distribution: str
    scale: float
    best_iteration: int

    def probabilities(self, frame: pd.DataFrame, horizons: list[int]) -> dict[int, dict[str, np.ndarray]]:
        matrix = xgb.DMatrix(self.encoder.transform(frame), enable_categorical=True)
        predicted_time = np.clip(self.booster.predict(matrix, iteration_range=(0, self.best_iteration + 1)), 1e-6, None)
        output = {}
        for horizon in horizons:
            z = (np.log(horizon) - np.log(predicted_time)) / self.scale
            if self.distribution == "normal":
                from scipy.special import ndtr

                p_h = ndtr(z)
            elif self.distribution == "extreme":
                p_h = 1 - np.exp(-np.exp(z))
            else:
                p_h = expit(z)
            p_h = np.clip(p_h, 0, 1)
            output[horizon] = {
                "hospitalized": p_h,
                "refused": np.zeros(len(frame)),
                "unresolved": 1 - p_h,
            }
        return output


def _aft_matrix(frame: pd.DataFrame, encoder: CategoricalFrameEncoder) -> xgb.DMatrix:
    matrix = xgb.DMatrix(encoder.transform(frame), enable_categorical=True)
    lower, upper = aft_bounds(frame)
    matrix.set_float_info("label_lower_bound", lower)
    matrix.set_float_info("label_upper_bound", upper)
    return matrix


def fit_aft(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    parameters: dict,
    *,
    threads: int,
    round_cap: int,
) -> AFTModel:
    encoder = CategoricalFrameEncoder.fit(train)
    dtrain, dvalid = _aft_matrix(train, encoder), _aft_matrix(validation, encoder)
    rounds = min(int(parameters["rounds"]), round_cap)
    params = {
        "objective": "survival:aft",
        "eval_metric": "aft-nloglik",
        "tree_method": "hist",
        "max_depth": int(parameters["max_depth"]),
        "learning_rate": float(parameters["learning_rate"]),
        "min_child_weight": float(parameters["min_child_weight"]),
        "aft_loss_distribution": parameters["aft_loss_distribution"],
        "aft_loss_distribution_scale": float(parameters["aft_loss_distribution_scale"]),
        "seed": 42,
        "nthread": threads,
    }
    booster = xgb.train(
        params,
        dtrain,
        rounds,
        evals=[(dvalid, "validation")],
        early_stopping_rounds=min(20, max(5, rounds // 3)),
        verbose_eval=False,
    )
    return AFTModel(
        booster,
        encoder,
        parameters["aft_loss_distribution"],
        float(parameters["aft_loss_distribution_scale"]),
        booster.best_iteration,
    )


def _expanded_hazard_rows(
    frame: pd.DataFrame,
    encoder: CategoricalFrameEncoder,
    edges: list[int],
    *,
    competing: bool,
) -> tuple[pd.DataFrame, np.ndarray]:
    base = encoder.transform(frame)
    matrices, labels = [], []
    duration = frame["journey_duration_days"].to_numpy(float)
    event = frame["journey_event"].to_numpy(int)
    for interval, (start, end) in enumerate(zip(edges[:-1], edges[1:], strict=True)):
        completed = duration >= end
        event_here = (event != 0) & (duration > start) & (duration <= end)
        if competing:
            usable = completed | event_here
            y = event[event_here | completed].copy()
        else:
            hosp_here = (event == EVENT_HOSPITALIZED) & (duration > start) & (duration <= end)
            competing_censor = (event == EVENT_REFUSED) & (duration <= end)
            usable = (completed & ~competing_censor) | hosp_here
            y = hosp_here[usable].astype(np.int8)
        if not usable.any():
            continue
        expanded = base.loc[usable].copy()
        expanded["time_interval"] = pd.Categorical(
            np.full(int(usable.sum()), str(interval)), categories=[str(i) for i in range(len(edges) - 1)]
        )
        matrices.append(expanded)
        labels.append(y if competing else y)
    return pd.concat(matrices, ignore_index=True), np.concatenate(labels)


@dataclass
class HazardModel:
    booster: lgb.Booster
    encoder: CategoricalFrameEncoder
    edges: list[int]
    competing: bool
    best_iteration: int

    def probabilities(self, frame: pd.DataFrame, horizons: list[int]) -> dict[int, dict[str, np.ndarray]]:
        base = self.encoder.transform(frame)
        survival = np.ones(len(frame))
        cif_h = np.zeros(len(frame))
        cif_r = np.zeros(len(frame))
        output = {}
        for interval, (_, end) in enumerate(zip(self.edges[:-1], self.edges[1:], strict=True)):
            matrix = base.copy()
            matrix["time_interval"] = pd.Categorical(
                np.full(len(frame), str(interval)), categories=[str(i) for i in range(len(self.edges) - 1)]
            )
            pred = self.booster.predict(matrix, num_iteration=self.best_iteration)
            if self.competing:
                h_h, h_r = pred[:, EVENT_HOSPITALIZED], pred[:, EVENT_REFUSED]
            else:
                h_h, h_r = np.asarray(pred), np.zeros(len(frame))
            cif_h += survival * h_h
            cif_r += survival * h_r
            survival *= np.clip(1 - h_h - h_r, 0, 1)
            if end in horizons:
                output[end] = {
                    "hospitalized": cif_h.copy(),
                    "refused": cif_r.copy(),
                    "unresolved": survival.copy(),
                }
        return output


def fit_hazard(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    parameters: dict,
    edges: list[int],
    *,
    competing: bool,
    threads: int,
    round_cap: int,
) -> HazardModel:
    encoder = CategoricalFrameEncoder.fit(train)
    X_train, y_train = _expanded_hazard_rows(train, encoder, edges, competing=competing)
    X_valid, y_valid = _expanded_hazard_rows(validation, encoder, edges, competing=competing)
    params = {
        "objective": "multiclass" if competing else "binary",
        "metric": "multi_logloss" if competing else "binary_logloss",
        "num_class": 3 if competing else 1,
        "num_leaves": int(parameters["num_leaves"]),
        "learning_rate": float(parameters["learning_rate"]),
        "min_data_in_leaf": int(parameters["min_data_in_leaf"]),
        "seed": 42,
        "num_threads": threads,
        "verbosity": -1,
        "deterministic": True,
        "force_row_wise": True,
    }
    rounds = min(int(parameters["rounds"]), round_cap)
    booster = lgb.train(
        params,
        lgb.Dataset(X_train, y_train, categorical_feature=[*CATEGORICAL, "time_interval"]),
        rounds,
        valid_sets=[lgb.Dataset(X_valid, y_valid, categorical_feature=[*CATEGORICAL, "time_interval"])],
        callbacks=[lgb.early_stopping(min(20, max(5, rounds // 3)), verbose=False)],
    )
    return HazardModel(booster, encoder, edges, competing, max(1, booster.best_iteration))


def legacy_wait_probabilities(
    artifacts_dir: Path, frame: pd.DataFrame, horizons: list[int]
) -> tuple[dict[int, dict[str, np.ndarray]], np.ndarray]:
    model = ReferralModel.load(artifacts_dir, "wait_time")
    wait = model.predict(frame)
    output = {}
    for horizon in horizons:
        p_h = (wait <= horizon).astype(float)
        output[horizon] = {
            "hospitalized": p_h,
            "refused": np.zeros(len(frame)),
            "unresolved": 1 - p_h,
        }
    return output, wait
