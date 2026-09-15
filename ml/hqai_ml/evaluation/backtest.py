"""Rolling-origin backtest runner and forecast metric tables."""

import datetime as dt
from collections.abc import Callable

import numpy as np
import pandas as pd

from hqai_ml.evaluation.metrics import wape


def rolling_origin(origins: list[dt.date], fit_predict: Callable[[dt.date], pd.DataFrame], log=print) -> pd.DataFrame:
    """Run fit_predict(origin) for each forecast origin (model sees only data before it); concatenate results."""
    frames = []
    for origin in origins:
        log(f"  backtest origin {origin} …")
        frame = fit_predict(origin)
        frame.insert(0, "origin", str(origin))
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def horizon_bucket(h: pd.Series) -> pd.Series:
    return np.where(h <= 7, "1–7", "8–14")


def error_table(ev: pd.DataFrame, group_cols: list[str], methods: dict[str, str], bias: bool = False) -> list[dict]:
    """WAPE and MAE per group for each method column (rows with any missing method value are dropped).

    bias=True adds the signed relative bias Σ(pred − y) / Σy per method.
    """
    cols = list(methods.values())
    ev = ev.dropna(subset=cols + ["y"])
    rows = []
    for keys, sub in ev.groupby(group_cols, sort=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(group_cols, keys, strict=True))
        row["n"] = int(len(sub))
        row["actual_total"] = float(sub["y"].sum())
        for label, col in methods.items():
            row[f"wape_{label}"] = wape(sub["y"], sub[col])
            row[f"mae_{label}"] = float(np.abs(sub["y"] - sub[col]).mean())
            if bias:
                total = sub["y"].sum()
                row[f"bias_{label}"] = float((sub[col] - sub["y"]).sum() / total) if total else None
        rows.append(row)
    return rows
