#!/usr/bin/env python3
"""Standalone predictor for the refusal_risk model: probability that a referral ends in refusal (LightGBM binary).

Works without the hospital-queue-ai repository. It needs lightgbm, pandas and numpy plus three files from this
folder: model.txt (native LightGBM model), features.json (column order) and categories.json (the category levels
seen in training). Categorical columns are encoded exactly as at training and serving time in the repository
(pandas Categorical over the stored levels, unseen levels become missing), so predictions are identical to the
repository's. predict() returns the probability of refusal (versus hospitalization) in [0, 1].

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
NAME = "refusal_risk"
MODEL_FILE = "model.txt"
OUTPUT = "pred_refusal_prob"


@dataclass
class Model:
    booster: lgb.Booster
    features: list[str]
    categories: dict[str, list[str]]
    meta: dict

    @property
    def categorical(self) -> list[str]:
        return list(self.categories)


def load(directory: str | Path = HERE) -> Model:
    """Load the native model file and its feature contract from a released folder."""
    directory = Path(directory)
    features = json.loads((directory / "features.json").read_text(encoding="utf-8"))["features"]
    categories = json.loads((directory / "categories.json").read_text(encoding="utf-8"))
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    return Model(lgb.Booster(model_file=str(directory / MODEL_FILE)), features, categories, meta)


def from_bundle(bundle: dict) -> Model:
    """The same model from bundle.joblib (a plain dict; see README)."""
    return Model(bundle["model"], list(bundle["features"]), dict(bundle["categories"]), dict(bundle["meta"]))


def encode(frame: pd.DataFrame, features: list[str], categories: dict[str, list[str]]) -> pd.DataFrame:
    """Feature frame with categoricals as pandas Categorical over the training levels (unseen -> NaN)."""
    X = frame[features].copy()
    for column, levels in categories.items():
        X[column] = pd.Categorical(X[column].astype("string").astype(object), categories=levels)
    for column in features:
        if column not in categories:
            X[column] = X[column].astype("float64")
    return X


def raw_score(frame: pd.DataFrame, model: Model) -> np.ndarray:
    """Log-odds of refusal."""
    return model.booster.predict(encode(frame, model.features, model.categories), raw_score=True)


def predict(frame: pd.DataFrame, model: Model | None = None) -> pd.DataFrame:
    """Probability of refusal for every row of `frame` (missing values allowed in every feature)."""
    model = model or load()
    probability = 1 / (1 + np.exp(-raw_score(frame, model)))
    return pd.DataFrame({OUTPUT: probability}, index=frame.index)


def read_input(path: str | Path, model: Model) -> pd.DataFrame:
    """CSV (optionally gzipped) with categorical codes read as text so that codes like 0011 keep their zeros."""
    return pd.read_csv(path, dtype=dict.fromkeys(model.categorical, "string"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="CSV with the feature columns listed in features.json")
    parser.add_argument("--output", required=True, help="CSV: the input's non-feature columns plus the prediction")
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
