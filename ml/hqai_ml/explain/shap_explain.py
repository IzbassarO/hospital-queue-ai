"""SHAP explanations for the referral models (TreeExplainer).

SHAP values are additive in the model's raw space (log1p(days) for wait time, log-odds for refusal
risk): raw = base + Σφ. For readable effects on the output scale (days, probability) every φ is
multiplied by the same secant slope of the link between the average and this prediction:
    slope    = (g(raw) − g(base)) / (raw − base)        g = expm1 or sigmoid
    effect_i = φ_i · slope
so the effects keep SHAP's signs and ordering and add up exactly to
"this prediction − the average prediction g(base)". When raw ≈ base the slope is g'(raw).
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import shap
import yaml

from hqai_ml.models.referral_model import ReferralModel

TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "configs" / "explain_templates.yaml"


@lru_cache
def load_templates(path: Path = TEMPLATES_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


_EXPLAINERS: dict[int, shap.TreeExplainer] = {}


def _explainer(model: ReferralModel) -> shap.TreeExplainer:
    key = id(model.booster)
    if key not in _EXPLAINERS:
        _EXPLAINERS[key] = shap.TreeExplainer(model.booster)
    return _EXPLAINERS[key]


def shap_matrix(model: ReferralModel, df: pd.DataFrame) -> tuple[np.ndarray, float]:
    """(φ [n_rows, n_features], expected value) in raw model space."""
    ex = _explainer(model)
    phi = ex.shap_values(model.X(df))
    if isinstance(phi, list):  # older shap returns one array per class for binary models
        phi = phi[-1]
    base = ex.expected_value
    base = float(np.ravel(base)[-1])
    return np.asarray(phi, dtype=float), base


def global_importance(model: ReferralModel, df: pd.DataFrame) -> list[dict]:
    phi, _ = shap_matrix(model, df)
    mean_abs = np.abs(phi).mean(axis=0)
    total = mean_abs.sum() or 1.0
    order = np.argsort(-mean_abs)
    return [{"feature": model.features[i], "mean_abs_shap": float(mean_abs[i]), "share": float(mean_abs[i] / total)}
            for i in order]


def _sigmoid(x):
    return 1 / (1 + np.exp(-x))


def effects(model: ReferralModel, raw: np.ndarray, phi: np.ndarray, base: float) -> np.ndarray:
    """Per-factor effect on the output scale (days, or probability); rows sum to g(raw) − g(base)."""
    g = _sigmoid if model.is_classifier else np.expm1
    diff = raw - base
    derivative = _sigmoid(raw) * (1 - _sigmoid(raw)) if model.is_classifier else np.exp(raw)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(np.abs(diff) > 1e-6, (g(raw) - g(base)) / diff, derivative)
    return phi * slope[:, None]


# ------------------------------------------------------------------ Russian text
def _num(x: float, decimals: int) -> str:
    return f"{x:,.{decimals}f}".replace(",", " ").replace(".", ",")


def _days_ru(x: float) -> str:
    if abs(x) < 1:
        return f"{'+' if x >= 0 else '−'}{_num(abs(x), 1)} дня"
    n = int(round(abs(x)))
    word = "день" if n % 10 == 1 and n % 100 != 11 else "дня" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "дней"
    return f"{'+' if x >= 0 else '−'}{n} {word}"


def format_value(feature: str, value, model: ReferralModel, tpl: dict) -> str:
    spec = tpl["features"].get(feature, {"format": "text"})
    if value is None or (isinstance(value, float) and np.isnan(value)) or value is pd.NA:
        return tpl["missing_value"]
    fmt = spec["format"]
    if fmt in ("region", "org", "profile"):
        name = model.display.get(fmt, {}).get(str(value))
        return f"{name} ({value})" if name else str(value)
    if fmt == "icd_chapter":
        return f"{value} — {tpl['icd_chapters'].get(str(value), '')}".rstrip(" —")
    if fmt == "weekday":
        return tpl["weekdays"][int(value) - 1]
    if fmt == "int":
        return _num(float(value), 0)
    if fmt == "float1":
        return _num(float(value), 1)
    if fmt == "percent":
        return f"{_num(100 * float(value), 1)}%"
    return str(value)


def format_effect(model: ReferralModel, effect: float, tpl: dict) -> str:
    if model.is_classifier:
        pp = 100 * effect
        return f"{'+' if pp >= 0 else '−'}{_num(abs(pp), 1)} п.п. {tpl['refusal_effect_suffix']}"
    return _days_ru(effect)


def _factors(model: ReferralModel, row, phi_row: np.ndarray, eff_row: np.ndarray, top_k: int, tpl: dict) -> list[dict]:
    """`row` is any mapping feature -> value (dict or pandas Series)."""
    order = np.argsort(-np.abs(phi_row))[:top_k]
    out = []
    for i in order:
        f = model.features[i]
        value = row[f]
        value_py = None if value is None or pd.isna(value) else (value.item() if hasattr(value, "item") else value)
        out.append({
            "feature": f,
            "value": value_py,
            "direction": "up" if phi_row[i] >= 0 else "down",
            "shap": round(float(phi_row[i]), 4),
            "effect": round(float(eff_row[i]), 4),
            "text": tpl["sentence"].format(label=tpl["features"].get(f, {}).get("label", f),
                                           value=format_value(f, value_py, model, tpl),
                                           effect=format_effect(model, float(eff_row[i]), tpl)),
        })
    return out


def explain_referral(model: ReferralModel, features_row: pd.Series | dict, top_k: int = 5) -> list[dict]:
    """Top-k factors of one referral: feature, value, direction, SHAP (raw space), effect (days / probability), Russian text."""
    row = pd.Series(features_row) if isinstance(features_row, dict) else features_row
    df = row.to_frame().T
    for c in model.features:  # restore dtypes lost by the row -> frame round trip
        if c not in model.categories:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    phi, base = shap_matrix(model, df)
    raw = model.raw_score(df)
    eff = effects(model, raw, phi, base)
    return _factors(model, row, phi[0], eff[0], top_k, load_templates())


def explain_batch(model: ReferralModel, df: pd.DataFrame, top_k: int = 5) -> list[list[dict]]:
    """explain_referral for many rows at once (one SHAP pass)."""
    phi, base = shap_matrix(model, df)
    raw = model.raw_score(df)
    eff = effects(model, raw, phi, base)
    tpl = load_templates()
    rows = df[model.features].astype(object).where(df[model.features].notna(), None).to_dict("records")
    return [_factors(model, rows[i], phi[i], eff[i], top_k, tpl) for i in range(len(rows))]
