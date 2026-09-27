#!/usr/bin/env python3
"""Standalone predictor for the patient_journey_aft model: probability that a referral is hospitalized within 7, 14
and 30 days (XGBoost accelerated-failure-time survival model, hospitalization-only estimand).

Works without the hospital-queue-ai repository. It needs xgboost, pandas and numpy plus the files in this folder:
model.json (native XGBoost model), features.json (column order), categories.json (category levels seen in training)
and inference.json (best iteration, AFT distribution and scale, horizons, per-horizon calibrators). Feature encoding
and the probability formula are the ones the repository's tournament code applies (pandas Categorical over the
stored levels, float32 numerics, iteration_range up to the best iteration, then P(T <= h) from the AFT
distribution), so outputs are identical to the repository's.

Outputs per row: pred_time_days (the AFT location, a time scale rather than an exact wait), and for each horizon h
p_hospitalized_{h}d_raw (model probability) and p_hospitalized_{h}d (after the calibrator fitted on the
calibration fold; this is the quantity the published Brier scores refer to). Refusal is treated as censoring, so
1 - p_hospitalized is "not hospitalized by h", not a refusal probability.

CLI:     python predict.py --input referrals.csv --output predictions.csv
Python:  from predict import load, predict; model = load(); predict(frame)   # frame: one row per referral
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

HERE = Path(__file__).resolve().parent
NAME = "patient_journey_aft"
MODEL_FILE = "model.json"
TIME_OUTPUT = "pred_time_days"
_erfc = np.frompyfunc(math.erfc, 1, 1)


@dataclass
class Model:
    booster: xgb.Booster
    features: list[str]
    categories: dict[str, list[str]]
    meta: dict
    inference: dict

    @property
    def categorical(self) -> list[str]:
        return list(self.categories)

    @property
    def horizons(self) -> list[int]:
        return [int(h) for h in self.inference["horizons"]]


def load(directory: str | Path = HERE) -> Model:
    """Load the native model file and its inference contract from a released folder."""
    directory = Path(directory)
    features = json.loads((directory / "features.json").read_text(encoding="utf-8"))["features"]
    categories = json.loads((directory / "categories.json").read_text(encoding="utf-8"))
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    inference = json.loads((directory / "inference.json").read_text(encoding="utf-8"))
    booster = xgb.Booster()
    booster.load_model(str(directory / MODEL_FILE))
    return Model(booster, features, categories, meta, inference)


def from_bundle(bundle: dict) -> Model:
    """The same model from bundle.joblib (a plain dict; see README)."""
    return Model(
        bundle["model"],
        list(bundle["features"]),
        dict(bundle["categories"]),
        dict(bundle["meta"]),
        dict(bundle["inference"]),
    )


def encode(frame: pd.DataFrame, features: list[str], categories: dict[str, list[str]]) -> pd.DataFrame:
    """Categoricals over the training levels (unseen -> missing); numerics coerced to float32."""
    output = pd.DataFrame(index=frame.index)
    for feature in features:
        if feature in categories:
            output[feature] = pd.Categorical(frame[feature].astype("string"), categories=categories[feature])
        else:
            output[feature] = pd.to_numeric(frame[feature], errors="coerce").astype("float32")
    return output


def normal_cdf(z: np.ndarray) -> np.ndarray:
    return 0.5 * _erfc(-np.asarray(z, dtype=float) / math.sqrt(2.0)).astype(float)


def event_probability(z: np.ndarray, distribution: str) -> np.ndarray:
    """P(log T <= log h) for the AFT error distribution used in training."""
    if distribution == "normal":
        return normal_cdf(z)
    if distribution == "extreme":
        return 1 - np.exp(-np.exp(z))
    return 1 / (1 + np.exp(-z))


def calibrate(probability: np.ndarray, calibrator: dict) -> np.ndarray:
    """Apply the stored calibrator (uncalibrated, sigmoid on the logit, or isotonic with clipping at the ends)."""
    p = np.clip(np.asarray(probability, dtype=float), 1e-6, 1 - 1e-6)
    method = calibrator["method"]
    if method == "uncalibrated":
        return p
    if method == "sigmoid":
        logit = np.log(p / (1 - p))
        return 1 / (1 + np.exp(-(calibrator["coefficient"] * logit + calibrator["intercept"])))
    if method == "isotonic":
        return np.interp(
            p, np.asarray(calibrator["x_thresholds"], float), np.asarray(calibrator["y_thresholds"], float)
        )
    raise ValueError(f"unknown calibration method {method!r}")


def predicted_time(frame: pd.DataFrame, model: Model) -> np.ndarray:
    matrix = xgb.DMatrix(encode(frame, model.features, model.categories), enable_categorical=True)
    best = int(model.inference["best_iteration"])
    return np.clip(model.booster.predict(matrix, iteration_range=(0, best + 1)), 1e-6, None)


def predict(frame: pd.DataFrame, model: Model | None = None) -> pd.DataFrame:
    """Time scale and raw + calibrated hospitalization probabilities per horizon for every row of `frame`."""
    model = model or load()
    time_days = predicted_time(frame, model)
    scale = float(model.inference["aft"]["scale"])
    distribution = model.inference["aft"]["distribution"]
    out = {TIME_OUTPUT: time_days.astype(float)}
    for horizon in model.horizons:
        z = (np.log(horizon) - np.log(time_days)) / scale
        raw = np.clip(event_probability(z, distribution), 0, 1)
        out[f"p_hospitalized_{horizon}d_raw"] = raw
        out[f"p_hospitalized_{horizon}d"] = calibrate(raw, model.inference["calibration"][str(horizon)])
    return pd.DataFrame(out, index=frame.index)


def read_input(path: str | Path, model: Model) -> pd.DataFrame:
    """CSV (optionally gzipped) with categorical codes read as text so that codes like 0011 keep their zeros."""
    return pd.read_csv(path, dtype=dict.fromkeys(model.categorical, "string"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="CSV with the feature columns listed in features.json")
    parser.add_argument("--output", required=True, help="CSV: the input's non-feature columns plus the predictions")
    parser.add_argument("--model-dir", default=str(HERE))
    args = parser.parse_args()
    model = load(args.model_dir)
    frame = read_input(args.input, model)
    missing = [column for column in model.features if column not in frame.columns]
    if missing:
        parser.error(f"input lacks feature columns: {missing}")
    passthrough = [column for column in frame.columns if column not in model.features]
    result = pd.concat([frame[passthrough], predict(frame, model)], axis=1)
    result.to_csv(args.output, index=False)
    print(f"{len(result)} rows -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
