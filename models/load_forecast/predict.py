#!/usr/bin/env python3
"""Standalone predictor for the load_forecast model: expected daily registrations and hospitalizations 1..14 days
ahead for a hospital x profile or region x profile series (two global LightGBM Poisson boosters, one per target).

Works without the hospital-queue-ai repository. It needs lightgbm, pandas and numpy plus the files in this folder:
model_registrations.txt and model_hospitalizations.txt (native LightGBM models), features.json (column order) and
categories.json (the category levels seen in training). Categorical columns are encoded exactly as in the repository
(pandas Categorical over the stored levels, unseen levels become missing), so predictions are identical.

One input row = one (series, forecast origin, horizon) triple whose lag and rolling features were computed from the
TARGET series being forecast, so rows for the two targets differ. The `target` column (registrations or
hospitalizations) chooses the booster; predict() returns the expected count for that row.

CLI:     python predict.py --input rows.csv --output predictions.csv [--target registrations]
Python:  from predict import load, predict; model = load(); predict(frame)   # frame has a `target` column
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
NAME = "load_forecast"
TARGETS = ("registrations", "hospitalizations")
MODEL_FILES = {target: f"model_{target}.txt" for target in TARGETS}
OUTPUT = "pred"


@dataclass
class Model:
    boosters: dict[str, lgb.Booster]
    features: list[str]
    categories: dict[str, list[str]]
    meta: dict

    @property
    def categorical(self) -> list[str]:
        return list(self.categories)


def load(directory: str | Path = HERE) -> Model:
    """Load both native model files and the feature contract from a released folder."""
    directory = Path(directory)
    features = json.loads((directory / "features.json").read_text(encoding="utf-8"))["features"]
    categories = json.loads((directory / "categories.json").read_text(encoding="utf-8"))
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    boosters = {target: lgb.Booster(model_file=str(directory / file)) for target, file in MODEL_FILES.items()}
    return Model(boosters, features, categories, meta)


def from_bundle(bundle: dict) -> Model:
    """The same model from bundle.joblib (a plain dict whose `model` maps target -> booster; see README)."""
    return Model(dict(bundle["model"]), list(bundle["features"]), dict(bundle["categories"]), dict(bundle["meta"]))


def encode(frame: pd.DataFrame, features: list[str], categories: dict[str, list[str]]) -> pd.DataFrame:
    """Feature frame with categoricals as pandas Categorical over the training levels (unseen -> NaN)."""
    X = frame[features].copy()
    for column, levels in categories.items():
        X[column] = pd.Categorical(X[column].astype("string").astype(object), categories=levels)
    for column in features:
        if column not in categories:
            X[column] = X[column].astype("float64")
    return X


def predict(frame: pd.DataFrame, model: Model | None = None, target: str | None = None) -> pd.DataFrame:
    """Expected daily count per row; `target` overrides the frame's `target` column when every row shares one."""
    model = model or load()
    if target is None:
        if "target" not in frame.columns:
            raise ValueError("pass target= or add a `target` column (registrations | hospitalizations)")
        targets = frame["target"].astype(str)
    else:
        targets = pd.Series(target, index=frame.index)
    unknown = sorted(set(targets) - set(TARGETS))
    if unknown:
        raise ValueError(f"unknown target(s) {unknown}; expected one of {list(TARGETS)}")
    out = np.full(len(frame), np.nan)
    for name in TARGETS:
        mask = (targets == name).to_numpy()
        if mask.any():
            out[mask] = model.boosters[name].predict(encode(frame[mask], model.features, model.categories))
    return pd.DataFrame({OUTPUT: out}, index=frame.index)


def read_input(path: str | Path, model: Model) -> pd.DataFrame:
    """CSV (optionally gzipped) with categorical codes read as text so that codes like 0011 keep their zeros."""
    return pd.read_csv(path, dtype=dict.fromkeys([*model.categorical, "target"], "string"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="CSV with the feature columns listed in features.json")
    parser.add_argument("--output", required=True, help="CSV: the input's non-feature columns plus `pred`")
    parser.add_argument("--target", choices=TARGETS, help="target of every row when the CSV has no `target` column")
    parser.add_argument("--model-dir", default=str(HERE))
    args = parser.parse_args()
    model = load(args.model_dir)
    frame = read_input(args.input, model)
    missing = [column for column in model.features if column not in frame.columns]
    if missing:
        parser.error(f"input lacks feature columns: {missing}")
    passthrough = [column for column in frame.columns if column not in model.features]
    result = pd.concat([frame[passthrough], predict(frame, model, args.target)], axis=1)
    result.to_csv(args.output, index=False)
    print(f"{len(result)} rows -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
