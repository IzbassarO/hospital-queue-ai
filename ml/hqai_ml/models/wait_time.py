"""Model A — wait time (days from registration to hospitalization) for referrals that are not same-day.

Target: wait_days, trained on log1p(wait_days) with L2 loss; evaluated in days.
"""

import numpy as np
import pandas as pd

from hqai_ml.evaluation.metrics import by_segment, regression_metrics
from hqai_ml.features.referral import CATEGORICAL, NUMERIC, SUSPECTED_LEAK
from hqai_ml.models import referral_training as rt
from hqai_ml.models.config import ModelConfig

NAME = "wait_time"
FEATURES = CATEGORICAL + NUMERIC
OBJECTIVE = {"objective": "regression", "metric": "l2"}
TARGET = "wait_days"


def population(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["outcome"] == "hospitalized") & (~df["same_day_registration"].astype(bool))]


def baselines(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    g = float(train[TARGET].median())
    pr = train.groupby(["profile_code", "region_code"])[TARGET].median().rename("b2")
    hp = train.groupby(["org_code", "profile_code"])[TARGET].median().rename("b3")
    t = (
        test[["profile_code", "region_code", "org_code"]]
        .join(pr, on=["profile_code", "region_code"])
        .join(hp, on=["org_code", "profile_code"])
    )
    b2 = t["b2"].fillna(g).to_numpy(float)
    b3 = t["b3"].fillna(pd.Series(b2, index=t.index)).to_numpy(float)
    return {
        "B1 global median": np.full(len(test), g),
        "B2 median profile × patient region": b2,
        "B3 median hospital × profile (fallback B2)": b3,
    }


def _fit(train, test, features, cfg, display):
    y = np.log1p(train[TARGET].to_numpy(float))
    return rt.fit_model(NAME, train, test, y, features, OBJECTIVE, cfg, display)


def train_and_evaluate(df: pd.DataFrame, cfg: ModelConfig, display: dict) -> dict:
    within = cfg.wait_time.within_days
    train, test = rt.split_population(population(df), cfg)
    fit = _fit(train, test, FEATURES, cfg, display)
    model = fit.model
    y = test[TARGET].to_numpy(float)
    pred = model.predict(test)
    base = baselines(train, test)
    preds = {"LightGBM": pred, **base}

    overall = [{"model": k, **regression_metrics(y, v, within)} for k, v in preds.items()]

    ev = test[["region_code", "profile_code"]].copy()
    ev["y"] = y
    for k, v in preds.items():
        ev[k] = v
    b3 = "B3 median hospital × profile (fallback B2)"

    def seg(sub):
        m, b = regression_metrics(sub["y"], sub["LightGBM"], within), regression_metrics(sub["y"], sub[b3], within)
        return {
            "n": m["n"],
            "mae_model": m["mae"],
            "mae_b1": regression_metrics(sub["y"], sub["B1 global median"])["mae"],
            "mae_b2": regression_metrics(sub["y"], sub["B2 median profile × patient region"])["mae"],
            "mae_b3": b["mae"],
            "wape_model": m["wape"],
            "wape_b3": b["wape"],
            f"within_{within}d_model": m[f"within_{within}d"],
            f"within_{within}d_b3": b[f"within_{within}d"],
            "spearman_model": m["spearman"],
            "spearman_b3": b["spearman"],
            "median_actual": float(np.median(sub["y"])),
        }

    regions, profiles = rt.region_and_profile_segments(test, cfg.wait_time.top_profiles)
    by_region = by_segment(ev, "region_code", seg, regions)
    by_profile = by_segment(ev, "profile_code", seg, profiles)

    # ablation: what the suspected-leak feature would add
    abl = _fit(train, test, FEATURES + SUSPECTED_LEAK, cfg, display)
    planned_alone = np.clip(
        test["planned_lag_days"].fillna(pd.Series(base["B2 median profile × patient region"], index=test.index)),
        0,
        None,
    )
    ablation = [
        {"model": "LightGBM (main, without planned_lag_days)", **regression_metrics(y, pred, within)},
        {"model": "LightGBM + planned_lag_days", **regression_metrics(y, abl.model.predict(test), within)},
        {"model": "planned_lag_days alone (as a prediction)", **regression_metrics(y, planned_alone, within)},
    ]

    return {
        "model": model,
        "best_iteration": fit.best_iteration,
        "metrics": {
            "population": {
                "definition": "hospitalized, same_day_registration = false",
                "train_rows": len(train),
                "test_rows": len(test),
                "train_median_wait": float(train[TARGET].median()),
                "test_median_wait": float(np.median(y)),
            },
            "best_iteration": fit.best_iteration,
            "overall": overall,
            "by_region": by_region,
            "by_profile": by_profile,
            "shap": rt.shap_report(model, test, cfg),
            "ablation_planned_lag": ablation,
            "examples": rt.examples(model, test, pred, TARGET, cfg),
        },
        "test_predictions": pd.DataFrame({"referral_id": test["referral_id"], "pred": pred}),
    }
