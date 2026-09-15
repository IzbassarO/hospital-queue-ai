"""Model B — probability that a referral ends in refusal (vs hospitalization)."""

import numpy as np
import pandas as pd

from hqai_ml.evaluation.metrics import by_segment, calibration_table, classification_metrics
from hqai_ml.features.referral import CATEGORICAL, NUMERIC, REFUSAL_EXTRA, SUSPECTED_LEAK
from hqai_ml.models import referral_training as rt
from hqai_ml.models.config import ModelConfig

NAME = "refusal_risk"
FEATURES = CATEGORICAL + NUMERIC + REFUSAL_EXTRA
OBJECTIVE = {"objective": "binary", "metric": "binary_logloss"}


def population(df: pd.DataFrame) -> pd.DataFrame:
    pop = df[df["outcome"].isin(["hospitalized", "refused"])].copy()
    pop["refused"] = (pop["outcome"] == "refused").astype(int)
    return pop


def baselines(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    g = float(train["refused"].mean())
    pr = train.groupby(["profile_code", "region_code"])["refused"].mean().rename("b2")
    hp = train.groupby(["org_code", "profile_code"])["refused"].mean().rename("b3")
    t = (
        test[["profile_code", "region_code", "org_code"]]
        .join(pr, on=["profile_code", "region_code"])
        .join(hp, on=["org_code", "profile_code"])
    )
    b2 = t["b2"].fillna(g).to_numpy(float)
    b3 = t["b3"].fillna(pd.Series(b2, index=t.index)).to_numpy(float)
    return {
        "B1 global rate": np.full(len(test), g),
        "B2 rate profile × patient region": b2,
        "B3 rate hospital × profile (fallback B2)": b3,
    }


def _fit(train, test, features, cfg, display):
    return rt.fit_model(NAME, train, test, train["refused"].to_numpy(float), features, OBJECTIVE, cfg, display)


def train_and_evaluate(df: pd.DataFrame, cfg: ModelConfig, display: dict) -> dict:
    top = cfg.refusal_risk.top_fraction
    train, test = rt.split_population(population(df), cfg)
    fit = _fit(train, test, FEATURES, cfg, display)
    model = fit.model
    y = test["refused"].to_numpy(int)
    prob = model.predict(test)
    base = baselines(train, test)
    preds = {"LightGBM": prob, **base}
    overall = [{"model": k, **classification_metrics(y, v, top)} for k, v in preds.items()]

    ev = test[["region_code", "profile_code"]].copy()
    ev["y"] = y
    for k, v in preds.items():
        ev[k] = v
    b3 = "B3 rate hospital × profile (fallback B2)"

    def seg(sub):
        m, b = classification_metrics(sub["y"], sub["LightGBM"], top), classification_metrics(sub["y"], sub[b3], top)
        return {
            "n": m["n"],
            "refusal_rate": m["base_rate"],
            "mean_pred_model": float(sub["LightGBM"].mean()),
            "roc_auc_model": m["roc_auc"],
            "roc_auc_b3": b["roc_auc"],
            "pr_auc_model": m["pr_auc"],
            "pr_auc_b3": b["pr_auc"],
            "brier_model": m["brier"],
            "brier_b3": b["brier"],
        }

    regions, profiles = rt.region_and_profile_segments(test, cfg.wait_time.top_profiles)

    abl = _fit(train, test, FEATURES + SUSPECTED_LEAK, cfg, display)
    ablation = [
        {"model": "LightGBM (main, without planned_lag_days)", **classification_metrics(y, prob, top)},
        {"model": "LightGBM + planned_lag_days", **classification_metrics(y, abl.model.predict(test), top)},
        {
            "model": "planned_dt missing (as a score)",
            **classification_metrics(y, test["planned_lag_days"].isna().astype(float).to_numpy(), top),
        },
    ]

    return {
        "model": model,
        "best_iteration": fit.best_iteration,
        "metrics": {
            "population": {
                "definition": "outcome in (hospitalized, refused)",
                "train_rows": len(train),
                "test_rows": len(test),
                "train_refusal_rate": float(train["refused"].mean()),
                "test_refusal_rate": float(y.mean()),
            },
            "best_iteration": fit.best_iteration,
            "overall": overall,
            "calibration_model": calibration_table(y, prob, cfg.refusal_risk.calibration_bins),
            "calibration_b3": calibration_table(y, base[b3], cfg.refusal_risk.calibration_bins),
            "by_region": by_segment(ev, "region_code", seg, regions),
            "by_profile": by_segment(ev, "profile_code", seg, profiles),
            "shap": rt.shap_report(model, test, cfg),
            "ablation_planned_lag": ablation,
            "examples": rt.examples(model, test, prob, "refused", cfg),
        },
        "test_predictions": pd.DataFrame({"referral_id": test["referral_id"], "pred": prob}),
    }
