#!/usr/bin/env python3
"""Standalone predictor for the flow_quantile model: p10 / p50 / p90 of daily registrations 1..14 days ahead for a
hospital x profile or region x profile series (three LightGBM quantile boosters per target, alpha 0.1, 0.5, 0.9).

Works without the hospital-queue-ai repository. It needs lightgbm, pandas and numpy plus the files in this folder:
model_<target>_p10.txt, _p50.txt, _p90.txt (native LightGBM models), categories_<target>.json (the category levels the
boosters were fitted with) and features.json (column order). Categorical columns are encoded exactly as in the
repository (pandas Categorical over the stored levels, unseen levels become missing), so predictions are identical.

One input row = one (series, forecast origin, horizon) triple whose lag and rolling features were computed from the
target series; the `target` column (or --target) chooses the booster set. Outputs per row: p10, p50, p90 (raw model
quantiles, the published scientific evidence) and p10_repaired, p50_repaired, p90_repaired (max(0) followed by a
cumulative maximum across the three quantiles: the serving variant that guarantees non-negative, non-crossing
intervals). Raw quantiles may be negative or cross; that is reported, not hidden.

CLI:     python predict.py --input rows.csv --output predictions.csv [--target registrations]
Python:  from predict import load, predict; model = load(); predict(frame)   # frame has a `target` column
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
NAME = "flow_quantile"
QUANTILE_COLUMNS = ("p10", "p50", "p90")
MODEL_PATTERN = re.compile(r"^model_(?P<target>.+)_p10\.txt$")


@dataclass
class Model:
    boosters: dict[str, dict[str, lgb.Booster]]  # target -> quantile column -> booster
    categories: dict[str, dict[str, list[str]]]  # target -> categorical column -> levels
    features: list[str]
    meta: dict

    @property
    def targets(self) -> list[str]:
        return sorted(self.boosters)

    @property
    def categorical(self) -> list[str]:
        return sorted({column for levels in self.categories.values() for column in levels})


def load(directory: str | Path = HERE) -> Model:
    """Load every shipped target's three boosters and their category levels from a released folder."""
    directory = Path(directory)
    features = json.loads((directory / "features.json").read_text(encoding="utf-8"))["features"]
    meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
    boosters, categories = {}, {}
    for path in sorted(directory.glob("model_*_p10.txt")):
        target = MODEL_PATTERN.match(path.name)["target"]
        boosters[target] = {
            column: lgb.Booster(model_file=str(directory / f"model_{target}_{column}.txt"))
            for column in QUANTILE_COLUMNS
        }
        categories[target] = json.loads((directory / f"categories_{target}.json").read_text(encoding="utf-8"))
    if not boosters:
        raise FileNotFoundError(f"no model_<target>_p10.txt in {directory}")
    return Model(boosters, categories, features, meta)


def encode(frame: pd.DataFrame, features: list[str], categories: dict[str, list[str]]) -> pd.DataFrame:
    """Feature frame with categoricals as pandas Categorical over the training levels (unseen -> NaN)."""
    X = frame[features].copy()
    for column, levels in categories.items():
        X[column] = pd.Categorical(X[column].astype("string").astype(object), categories=levels)
    for column in features:
        if column not in categories:
            X[column] = X[column].astype("float64")
    return X


def repair(values: np.ndarray) -> np.ndarray:
    """Serving variant: clip at zero, then enforce p10 <= p50 <= p90 with a cumulative maximum."""
    return np.maximum.accumulate(np.maximum(np.asarray(values, dtype=float), 0.0), axis=-1)


def predict(frame: pd.DataFrame, model: Model | None = None, target: str | None = None) -> pd.DataFrame:
    """Raw and repaired p10/p50/p90 per row; `target` overrides the frame's `target` column."""
    model = model or load()
    if target is None:
        if "target" not in frame.columns:
            raise ValueError(f"pass target= or add a `target` column ({' | '.join(model.targets)})")
        targets = frame["target"].astype(str)
    else:
        targets = pd.Series(target, index=frame.index)
    unknown = sorted(set(targets) - set(model.targets))
    if unknown:
        raise ValueError(f"unknown target(s) {unknown}; shipped targets: {model.targets}")
    raw = np.full((len(frame), 3), np.nan)
    for name in model.targets:
        mask = (targets == name).to_numpy()
        if mask.any():
            encoded = encode(frame[mask], model.features, model.categories[name])
            for j, column in enumerate(QUANTILE_COLUMNS):
                raw[mask, j] = model.boosters[name][column].predict(encoded)
    repaired = repair(raw)
    out = {column: raw[:, j] for j, column in enumerate(QUANTILE_COLUMNS)}
    out.update({f"{column}_repaired": repaired[:, j] for j, column in enumerate(QUANTILE_COLUMNS)})
    return pd.DataFrame(out, index=frame.index)


def read_input(path: str | Path, model: Model) -> pd.DataFrame:
    """CSV (optionally gzipped) with categorical codes read as text so that codes like 0011 keep their zeros."""
    return pd.read_csv(path, dtype=dict.fromkeys([*model.categorical, "target"], "string"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="CSV with the feature columns listed in features.json")
    parser.add_argument("--output", required=True, help="CSV: the input's non-feature columns plus the quantiles")
    parser.add_argument("--target", help="target of every row when the CSV has no `target` column")
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
