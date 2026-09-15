"""Metric functions. All return plain floats (None when undefined) so results serialize to JSON."""

import math

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def _f(x) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def wape(y, pred) -> float | None:
    y, pred = np.asarray(y, float), np.asarray(pred, float)
    denom = np.abs(y).sum()
    return _f(np.abs(y - pred).sum() / denom) if denom > 0 else None


def regression_metrics(y, pred, within_days: int = 7) -> dict:
    y, pred = np.asarray(y, float), np.asarray(pred, float)
    err = np.abs(y - pred)
    rho = None
    if len(y) > 2 and np.ptp(pred) > 0 and np.ptp(y) > 0:
        rho = _f(spearmanr(y, pred).statistic)
    return {
        "n": int(len(y)),
        "mae": _f(err.mean()) if len(y) else None,
        "median_ae": _f(np.median(err)) if len(y) else None,
        "wape": wape(y, pred),
        f"within_{within_days}d": _f((err <= within_days).mean()) if len(y) else None,
        "spearman": rho,
    }


def classification_metrics(y, prob, top_fraction: float = 0.10) -> dict:
    y, prob = np.asarray(y, int), np.asarray(prob, float)
    both = len(np.unique(y)) == 2
    k = max(1, int(round(top_fraction * len(y))))
    # rank by probability; ties broken by a stable sort so constant scores give a random-like top set
    top = np.argsort(-prob, kind="stable")[:k]
    tp = y[top].sum()
    return {
        "n": int(len(y)),
        "base_rate": _f(y.mean()) if len(y) else None,
        "roc_auc": _f(roc_auc_score(y, prob)) if both else None,
        "pr_auc": _f(average_precision_score(y, prob)) if both else None,
        "brier": _f(brier_score_loss(y, prob)) if len(y) else None,
        "precision_top": _f(tp / k),
        "recall_top": _f(tp / y.sum()) if y.sum() else None,
    }


def calibration_table(y, prob, bins: int = 10) -> list[dict]:
    """Equal-frequency bins of predicted probability: mean predicted vs observed rate."""
    df = pd.DataFrame({"y": np.asarray(y, int), "p": np.asarray(prob, float)})
    df["bin"] = pd.qcut(df["p"].rank(method="first"), bins, labels=False)
    out = (
        df.groupby("bin")
        .agg(n=("y", "size"), p_min=("p", "min"), p_max=("p", "max"), mean_pred=("p", "mean"), observed=("y", "mean"))
        .reset_index()
    )
    return [{k: (int(v) if k in ("bin", "n") else float(v)) for k, v in r.items()} for r in out.to_dict("records")]


def by_segment(df: pd.DataFrame, segment_col: str, fn, segments=None) -> list[dict]:
    """Apply fn(sub_df) -> dict for each segment value (optionally a fixed list, in that order)."""
    values = segments if segments is not None else sorted(df[segment_col].dropna().unique())
    rows = []
    for v in values:
        sub = df[df[segment_col] == v]
        if len(sub):
            rows.append({"segment": v, **fn(sub)})
    return rows
