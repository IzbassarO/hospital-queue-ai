"""Shared training/evaluation flow for the referral models (A and B)."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from hqai_ml.evaluation.split import holdout_mask, temporal_masks
from hqai_ml.explain.shap_explain import explain_batch, global_importance, shap_matrix
from hqai_ml.features.referral import CATEGORICAL
from hqai_ml.models.config import ModelConfig
from hqai_ml.models.lgbm import encode, fit_categories, fit_early_stopped
from hqai_ml.models.referral_model import ReferralModel


@dataclass
class FitResult:
    model: ReferralModel
    best_iteration: int
    train: pd.DataFrame
    test: pd.DataFrame


def split_population(pop: pd.DataFrame, cfg: ModelConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_mask, test_mask = temporal_masks(pop["registration_date"], cfg.split)
    train = pop[train_mask].sort_values(["registration_date", "referral_id"]).reset_index(drop=True)
    test = pop[test_mask].sort_values(["registration_date", "referral_id"]).reset_index(drop=True)
    return train, test


def fit_model(
    name: str,
    train: pd.DataFrame,
    test: pd.DataFrame,
    y_train: np.ndarray,
    features: list[str],
    objective: dict,
    cfg: ModelConfig,
    display: dict,
) -> FitResult:
    categorical = [c for c in features if c in CATEGORICAL]
    categories = fit_categories(train, categorical)
    X = encode(train, features, categories)
    holdout = holdout_mask(train["registration_date"], cfg.split.train_end, cfg.early_stopping.holdout_days).to_numpy()
    params = {**cfg.lightgbm, **objective}
    booster, best = fit_early_stopped(
        X, y_train, holdout, params, categorical, cfg.early_stopping.max_rounds, cfg.early_stopping.patience
    )
    model = ReferralModel(name=name, booster=booster, features=features, categories=categories, display=display)
    return FitResult(model, best, train, test)


def shap_report(model: ReferralModel, test: pd.DataFrame, cfg: ModelConfig) -> dict:
    sample = test.sample(n=min(cfg.explain.shap_sample, len(test)), random_state=42)
    importance = global_importance(model, sample)
    # additivity check: base + Σφ must reproduce the raw prediction
    phi, base = shap_matrix(model, sample.head(2000))
    err = float(np.abs(base + phi.sum(axis=1) - model.raw_score(sample.head(2000))).max())
    return {"importance": importance, "sample_size": len(sample), "additivity_max_abs_error": err}


def examples(
    model: ReferralModel, test: pd.DataFrame, pred: np.ndarray, actual_col: str, cfg: ModelConfig
) -> list[dict]:
    """Explanations for the test referrals whose prediction is closest to the 10th/50th/90th percentile."""
    out = []
    for q in (0.9, 0.5, 0.1):
        i = int(np.argmin(np.abs(pred - np.quantile(pred, q))))
        row = test.iloc[[i]]
        out.append(
            {
                "quantile": q,
                "referral_id": int(row["referral_id"].iloc[0]),
                "registration_date": str(row["registration_date"].iloc[0]),
                "profile_code": row["profile_code"].iloc[0],
                "org_code": row["org_code"].iloc[0],
                "prediction": float(pred[i]),
                "actual": None if pd.isna(row[actual_col].iloc[0]) else float(row[actual_col].iloc[0]),
                "factors": explain_batch(model, row, cfg.explain.top_k)[0],
            }
        )
    return out


def region_and_profile_segments(test: pd.DataFrame, top_profiles: int) -> tuple[list[str], list[str]]:
    regions = sorted(test["region_code"].dropna().unique())
    profiles = test["profile_code"].value_counts().head(top_profiles).index.tolist()
    return regions, profiles
