#!/usr/bin/env python3
"""Standalone predictor for the patient_journey_hazard model: probability that a referral is hospitalized within 7,
14 and 30 days (LightGBM discrete-time hazard over fixed day intervals, hospitalization-only estimand).

Works without the hospital-queue-ai repository. It needs lightgbm, pandas and numpy plus the files in this folder:
model.txt (native LightGBM model), features.json (column order), categories.json (category levels seen in training)
and inference.json (interval edges, number of iterations, horizons, per-horizon calibrators). Feature encoding and
the hazard-to-probability recursion are the ones the repository's tournament code applies (pandas Categorical over
the stored levels, float32 numerics, one expanded row per interval with the `time_interval` category, cumulative
incidence = sum over intervals of survival x hazard), so outputs are identical to the repository's.

Outputs per row and horizon h: p_hospitalized_{h}d_raw (model cumulative incidence) and p_hospitalized_{h}d (after
the calibrator fitted on the calibration fold; the published Brier scores refer to this quantity). Refusal is a
competing censor, not a predicted cause: 1 - p_hospitalized is "not hospitalized by h", not a refusal probability.

CLI:     python predict.py --input referrals.csv --output predictions.csv
Python:  from predict import load, predict; model = load(); predict(frame)   # frame: one row per referral
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
NAME = "patient_journey_hazard"
MODEL_FILE = "model.txt"
INTERVAL_COLUMN = "time_interval"


@dataclass
class Model:
    booster: lgb.Booster
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

    @property
    def edges(self) -> list[int]:
        return [int(edge) for edge in self.inference["hazard"]["time_bins"]]


def load(directory: str | Path = HERE) -> Model:
    """Load the native model file and its inference contract from a released folder."""
    directory = Path(directory)
    features = json.loads((directory / "features.json").read_text(encoding="utf-8"))["features"]
    categories = json.loads((directory / "categories.json").read_text(encoding="utf-8"))
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    inference = json.loads((directory / "inference.json").read_text(encoding="utf-8"))
    return Model(lgb.Booster(model_file=str(directory / MODEL_FILE)), features, categories, meta, inference)


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


def cumulative_incidence(frame: pd.DataFrame, model: Model) -> dict[int, np.ndarray]:
    """Raw P(hospitalized by h) for every horizon that is an interval edge, from the per-interval hazards."""
    base = encode(frame, model.features, model.categories)
    edges = model.edges
    interval_levels = [str(i) for i in range(len(edges) - 1)]
    iterations = int(model.inference["hazard"]["num_iteration"])
    survival = np.ones(len(frame))
    incidence = np.zeros(len(frame))
    out = {}
    for interval, end in enumerate(edges[1:]):
        matrix = base.copy()
        matrix[INTERVAL_COLUMN] = pd.Categorical(np.full(len(frame), str(interval)), categories=interval_levels)
        hazard = np.asarray(model.booster.predict(matrix, num_iteration=iterations))
        incidence += survival * hazard
        survival *= np.clip(1 - hazard, 0, 1)
        if end in model.horizons:
            out[end] = incidence.copy()
    return out


def predict(frame: pd.DataFrame, model: Model | None = None) -> pd.DataFrame:
    """Raw and calibrated hospitalization probabilities per horizon for every row of `frame`."""
    model = model or load()
    raw = cumulative_incidence(frame, model)
    out = {}
    for horizon in model.horizons:
        out[f"p_hospitalized_{horizon}d_raw"] = raw[horizon]
        out[f"p_hospitalized_{horizon}d"] = calibrate(raw[horizon], model.inference["calibration"][str(horizon)])
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
