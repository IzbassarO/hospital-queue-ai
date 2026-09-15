"""LightGBM helpers shared by the models: stable categorical encoding and early-stopped fitting."""
import lightgbm as lgb
import numpy as np
import pandas as pd


def fit_categories(df: pd.DataFrame, categorical: list[str]) -> dict[str, list[str]]:
    """Category levels seen in training; stored with the model so predict uses identical codes."""
    return {c: sorted(df[c].dropna().astype(str).unique().tolist()) for c in categorical}


def encode(df: pd.DataFrame, features: list[str], categories: dict[str, list[str]]) -> pd.DataFrame:
    """Feature frame with categoricals as pandas Categorical over the training levels (unseen -> NaN)."""
    X = df[features].copy()
    for c, levels in categories.items():
        X[c] = pd.Categorical(X[c].astype("string").astype(object), categories=levels)
    for c in features:
        if c not in categories:
            X[c] = X[c].astype("float64")
    return X


def fit_early_stopped(X: pd.DataFrame, y: np.ndarray, holdout: np.ndarray, params: dict, categorical: list[str],
                      max_rounds: int, patience: int) -> tuple[lgb.Booster, int]:
    """Pick the number of rounds on a temporal holdout, then refit on all rows with that many rounds."""
    fit_rows, hold_rows = ~holdout, holdout
    d_fit = lgb.Dataset(X[fit_rows], y[fit_rows], categorical_feature=categorical, free_raw_data=False)
    d_hold = lgb.Dataset(X[hold_rows], y[hold_rows], categorical_feature=categorical, reference=d_fit)
    probe = lgb.train(params, d_fit, num_boost_round=max_rounds, valid_sets=[d_hold],
                      callbacks=[lgb.early_stopping(patience, verbose=False)])
    best = max(1, probe.best_iteration)
    full = lgb.train(params, lgb.Dataset(X, y, categorical_feature=categorical), num_boost_round=best)
    return full, best
