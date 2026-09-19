"""Leakage-safe probabilistic flow evidence for p10/p50/p90 daily counts."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable

import lightgbm as lgb
import numpy as np
import pandas as pd

from hqai_ml.features.load import SERIES_CATEGORICAL, Panel, build_rows, feature_names
from hqai_ml.flow_forecast.config import FlowQuantileConfig
from hqai_ml.flow_forecast.evidence import (
    _add_national_aggregates,
    _fallback_predictions,
    _history_metadata,
    baseline_arrays,
    combine_panels,
    support_mask,
)
from hqai_ml.models.config import ModelConfig
from hqai_ml.models.lgbm import encode, fit_categories

QUANTILES = (0.1, 0.5, 0.9)
QUANTILE_COLUMNS = {0.1: "p10", 0.5: "p50", 0.9: "p90"}
PUBLIC_TARGETS = {"registrations": "registrations", "hospitalizations": "cohort_hospitalizations"}
INTERNAL_TARGETS = {public: internal for internal, public in PUBLIC_TARGETS.items()}
BASELINE = "probabilistic_recent_seasonal_average"
RAW_VARIANT = "raw"
REPAIRED_VARIANT = "repaired_nonnegative_monotone"
NATIONAL_PROXY = "region_quantile_sum_proxy"
EPSILON = 1e-9


def pinball_loss(y: np.ndarray, prediction: np.ndarray, quantile: float) -> np.ndarray:
    if not 0 < quantile < 1:
        raise ValueError("quantile must lie strictly between zero and one")
    error = np.asarray(y, dtype=float) - np.asarray(prediction, dtype=float)
    return np.maximum(quantile * error, (quantile - 1.0) * error)


def interval_score_80(y: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    """Central 80% interval score; crossed raw intervals remain unmodified and detectable."""
    alpha = 0.2
    y, lower, upper = (np.asarray(values, dtype=float) for values in (y, lower, upper))
    return upper - lower + (2.0 / alpha) * (lower - y) * (y < lower) + (2.0 / alpha) * (y - upper) * (y > upper)


def weighted_interval_score_80(
    y: np.ndarray,
    lower: np.ndarray,
    median: np.ndarray,
    upper: np.ndarray,
) -> np.ndarray:
    """WIS with one central 80% interval and the median, normalized by K + 0.5."""
    return (0.5 * np.abs(np.asarray(y) - np.asarray(median)) + 0.1 * interval_score_80(y, lower, upper)) / 1.5


def quantile_crossing(lower: np.ndarray, median: np.ndarray, upper: np.ndarray) -> np.ndarray:
    return (np.asarray(lower) > np.asarray(median)) | (np.asarray(median) > np.asarray(upper))


def empirical_interval_coverage(y: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> float:
    y, lower, upper = (np.asarray(values, dtype=float) for values in (y, lower, upper))
    return float(((lower <= y) & (y <= upper)).mean())


def interval_width(lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    return np.asarray(upper, dtype=float) - np.asarray(lower, dtype=float)


def negative_output_rate(lower: np.ndarray, median: np.ndarray, upper: np.ndarray) -> float:
    values = np.column_stack([lower, median, upper]).astype(float)
    return float((values < 0).mean())


def repair_quantiles(values: np.ndarray) -> np.ndarray:
    """Explicit projection used only for the operational variant; raw values remain separate."""
    array = np.asarray(values, dtype=float)
    if array.shape[-1] != 3:
        raise ValueError("quantile repair expects p10, p50, p90 in the final dimension")
    return np.maximum.accumulate(np.maximum(array, 0.0), axis=-1)


def empirical_residual_predictions(
    panel: Panel,
    target: str,
    origin_index: int,
    config: FlowQuantileConfig,
) -> tuple[dict[float, dict[tuple[str, int], float]], dict]:
    """Recent-seasonal point forecast plus only residuals whose target date is observed by origin."""
    values = panel.target(target)
    point = baseline_arrays(panel, target, origin_index, config)["recent_seasonal_average"]
    predictions = {quantile: {} for quantile in QUANTILES}
    sample_counts = []
    maximum_target_index = -1
    for horizon in range(1, config.horizon + 1):
        weekly_lag = 7 * math.ceil(horizon / 7)
        first_legal_cutoff = weekly_lag - horizon
        last_cutoff = origin_index - horizon
        first_cutoff = max(
            first_legal_cutoff,
            last_cutoff - config.residual_uncertainty.window_days + 1,
        )
        cutoffs = list(range(first_cutoff, last_cutoff + 1))
        if len(cutoffs) < config.residual_uncertainty.minimum_samples:
            raise ValueError(
                f"only {len(cutoffs)} legal residuals for horizon {horizon}; "
                f"need {config.residual_uncertainty.minimum_samples}"
            )
        residual_columns = []
        for cutoff in cutoffs:
            latest = cutoff + horizon - weekly_lag
            indices = [latest - 7 * offset for offset in range(config.baselines.recent_seasonal_periods)]
            available = [index for index in indices if index >= 0]
            historical_point = values[:, available].mean(axis=1)
            target_index = cutoff + horizon
            if target_index > origin_index:
                raise ValueError("residual calibration target crosses the forecast origin")
            maximum_target_index = max(maximum_target_index, target_index)
            residual_columns.append(values[:, target_index] - historical_point)
        residuals = np.column_stack(residual_columns)
        sample_counts.append(len(cutoffs))
        for quantile in QUANTILES:
            adjusted = point[:, horizon - 1] + np.quantile(residuals, quantile, axis=1, method="linear")
            for series_id, value in zip(panel.meta["series_id"], adjusted, strict=True):
                predictions[quantile][(str(series_id), horizon)] = float(value)
    return predictions, {
        "method": config.residual_uncertainty.method,
        "window_days": config.residual_uncertainty.window_days,
        "minimum_samples": min(sample_counts),
        "maximum_samples": max(sample_counts),
        "maximum_calibration_target_date": str(panel.dates[maximum_target_index]),
        "forecast_origin": str(panel.dates[origin_index]),
        "targets_at_or_before_origin": maximum_target_index <= origin_index,
    }


def fit_quantile_target(
    panel: Panel,
    target: str,
    origin_index: int,
    quantile: float,
    categories: dict[str, list[str]],
    config: FlowQuantileConfig,
    model_config: ModelConfig,
) -> lgb.Booster:
    lf = model_config.load_forecast
    rows = build_rows(
        panel,
        target,
        list(range(6, origin_index)),
        config.horizon,
        lf.lags,
        lf.rolling,
        set(lf.holidays),
        max_target_index=origin_index,
    )
    features = feature_names(lf.lags, lf.rolling)
    parameters = {
        **model_config.lightgbm,
        "objective": "quantile",
        "metric": "quantile",
        "alpha": quantile,
    }
    return lgb.train(
        parameters,
        lgb.Dataset(
            encode(rows, features, categories),
            rows["y"].to_numpy(float),
            categorical_feature=SERIES_CATEGORICAL,
        ),
        num_boost_round=config.challenger.rounds,
    )


def direct_quantile_predictions(
    panel: Panel,
    target: str,
    origin_index: int,
    config: FlowQuantileConfig,
    model_config: ModelConfig,
) -> dict[float, dict[tuple[str, int], float]]:
    categories = fit_categories(panel.meta, SERIES_CATEGORICAL)
    lf = model_config.load_forecast
    rows = build_rows(
        panel,
        target,
        [origin_index],
        config.horizon,
        lf.lags,
        lf.rolling,
        set(lf.holidays),
        max_target_index=None,
    )
    features = feature_names(lf.lags, lf.rolling)
    encoded = encode(rows, features, categories)
    output = {}
    for quantile in QUANTILES:
        booster = fit_quantile_target(panel, target, origin_index, quantile, categories, config, model_config)
        output[quantile] = {
            (str(series_id), int(horizon)): float(prediction)
            for series_id, horizon, prediction in zip(
                rows["series_id"],
                rows["horizon"],
                booster.predict(encoded),
                strict=True,
            )
        }
    return output


def _apply_hierarchy_fallback(
    direct_by_quantile: dict[float, dict[tuple[str, int], float]],
    panels: dict[str, Panel],
    all_panel: Panel,
    supported: dict[str, bool],
    target: str,
    origin_index: int,
    config: FlowQuantileConfig,
) -> tuple[dict[float, dict[tuple[str, int], float]], dict[str, str]]:
    output = {}
    fallback_reference = None
    for quantile in QUANTILES:
        direct = direct_by_quantile[quantile]
        _add_national_aggregates(direct, panels["region"], panels["national"], config.horizon)
        predictions, fallback = _fallback_predictions(
            all_panel,
            direct,
            supported,
            target,
            origin_index,
            config,
        )
        for series_id in panels["national"].meta["series_id"]:
            fallback[series_id] = NATIONAL_PROXY
        if fallback_reference is not None and fallback != fallback_reference:
            raise ValueError("quantile-specific fallback provenance diverged")
        fallback_reference = fallback
        output[quantile] = predictions
    return output, fallback_reference or {}


def _prediction_frame(
    metadata: pd.DataFrame,
    predictions: dict[float, dict[tuple[str, int], float]],
    fallback: dict[str, str],
    candidate: str,
    calibration_id: str,
) -> pd.DataFrame:
    frame = metadata.copy()
    for quantile, column in QUANTILE_COLUMNS.items():
        frame[column] = [
            predictions[quantile][(str(series_id), int(horizon))]
            for series_id, horizon in zip(frame["series_id"], frame["horizon"], strict=True)
        ]
    frame["candidate"] = candidate
    frame["fallback_level"] = frame["series_id"].map(fallback)
    direct_source = "statistical_residual_baseline" if candidate == BASELINE else "direct_quantile_ml"
    frame["prediction_source"] = direct_source
    frame.loc[frame["fallback_level"] == "region_profile_share", "prediction_source"] = f"parent_scaled_{direct_source}"
    own_history = frame["fallback_level"].isin(["own_history_zero", "own_history_seasonal"])
    frame.loc[own_history, "prediction_source"] = "deterministic_own_history_fallback"
    national_proxy = frame["fallback_level"] == NATIONAL_PROXY
    frame.loc[national_proxy, "prediction_source"] = NATIONAL_PROXY
    frame["fallback_level"] = frame["fallback_level"].replace({"direct_model": "none"})
    frame["aggregation_method"] = np.where(frame["level"] == "national", NATIONAL_PROXY, "none")
    frame["uncertainty_support"] = np.where(
        own_history,
        "degenerate_interval_no_estimated_uncertainty_support",
        "estimated",
    )
    frame["calibration_id"] = calibration_id
    frame["variant"] = RAW_VARIANT
    repaired = frame.copy()
    repaired[["p10", "p50", "p90"]] = repair_quantiles(repaired[["p10", "p50", "p90"]].to_numpy(float))
    repaired["variant"] = REPAIRED_VARIANT
    if (repaired[["p10", "p50", "p90"]].to_numpy(float) < 0).any():
        raise ValueError("operational quantile forecasts must be non-negative")
    return pd.concat([frame, repaired], ignore_index=True)


def evaluate_quantile_origin(
    panels: dict[str, Panel],
    origin: dt.date,
    phase: str,
    config: FlowQuantileConfig,
    model_config: ModelConfig,
    calibration_id: str,
) -> tuple[pd.DataFrame, list[dict]]:
    all_panel = combine_panels(panels.values())
    origin_index = all_panel.index_of(origin)
    frames = []
    calibration_audits = []
    for public_target in config.targets:
        target = INTERNAL_TARGETS[public_target]
        masks = {level: support_mask(panel, target, origin_index, config) for level, panel in panels.items()}
        supported_panels = [
            panel.subset(masks[level]) for level, panel in panels.items() if level != "national" and masks[level].any()
        ]
        direct_panel = combine_panels(supported_panels)
        supported = {
            str(series_id): bool(flag)
            for level, panel in panels.items()
            for series_id, flag in zip(panel.meta["series_id"], masks[level], strict=True)
        }
        baseline_direct, calibration_audit = empirical_residual_predictions(direct_panel, target, origin_index, config)
        calibration_audits.append({"target": public_target} | calibration_audit)
        baseline_predictions, baseline_fallback = _apply_hierarchy_fallback(
            baseline_direct,
            panels,
            all_panel,
            supported,
            target,
            origin_index,
            config,
        )
        model_direct = direct_quantile_predictions(direct_panel, target, origin_index, config, model_config)
        model_predictions, model_fallback = _apply_hierarchy_fallback(
            model_direct,
            panels,
            all_panel,
            supported,
            target,
            origin_index,
            config,
        )
        history = _history_metadata(all_panel, target, origin_index, config)
        repeated = history.loc[history.index.repeat(config.horizon)].reset_index(drop=True)
        repeated["horizon"] = np.tile(np.arange(1, config.horizon + 1), len(all_panel.meta))
        repeated["target_date"] = [origin + dt.timedelta(days=int(h)) for h in repeated["horizon"]]
        actual = all_panel.target(target)[:, origin_index + 1 : origin_index + config.horizon + 1]
        repeated["y"] = actual.reshape(-1)
        repeated["target"] = public_target
        repeated["origin"] = origin
        repeated["phase"] = phase
        repeated["supported"] = repeated["series_id"].map(supported)
        frames.extend(
            [
                _prediction_frame(
                    repeated,
                    baseline_predictions,
                    baseline_fallback,
                    BASELINE,
                    calibration_id,
                ),
                _prediction_frame(
                    repeated,
                    model_predictions,
                    model_fallback,
                    config.challenger.id,
                    "not_applicable_direct_quantile_model",
                ),
            ]
        )
    result = pd.concat(frames, ignore_index=True)
    result["origin"] = pd.to_datetime(result["origin"])
    result["target_date"] = pd.to_datetime(result["target_date"])
    result["horizon"] = result["horizon"].astype("int16")
    return result, calibration_audits


def probabilistic_metric_record(frame: pd.DataFrame) -> dict:
    if frame.empty:
        raise ValueError("cannot score an empty probabilistic evaluation frame")
    work = frame.copy()
    y = work["y"].to_numpy(float)
    work["pinball_p10"] = pinball_loss(y, work["p10"].to_numpy(float), 0.1)
    work["pinball_p50"] = pinball_loss(y, work["p50"].to_numpy(float), 0.5)
    work["pinball_p90"] = pinball_loss(y, work["p90"].to_numpy(float), 0.9)
    work["mean_pinball"] = work[["pinball_p10", "pinball_p50", "pinball_p90"]].mean(axis=1)
    work["wis_80"] = weighted_interval_score_80(
        y,
        work["p10"].to_numpy(float),
        work["p50"].to_numpy(float),
        work["p90"].to_numpy(float),
    )
    work["covered_80"] = (work["p10"] <= work["y"]) & (work["y"] <= work["p90"])
    work["interval_width_80"] = interval_width(work["p10"], work["p90"])
    work["p50_absolute_error"] = np.abs(work["y"] - work["p50"])
    work["crossed"] = quantile_crossing(work["p10"], work["p50"], work["p90"])
    squared_scaled = np.full(len(work), np.nan)
    positive_scale = work["rmsse_scale"].to_numpy(float) > 0
    np.divide(
        (work["y"].to_numpy(float) - work["p50"].to_numpy(float)) ** 2,
        work["rmsse_scale"].to_numpy(float),
        out=squared_scaled,
        where=positive_scale,
    )
    work["scaled_squared_error"] = squared_scaled
    per_series = (
        work.groupby("series_id", sort=False, observed=True)
        .agg(
            pinball_p10=("pinball_p10", "mean"),
            pinball_p50=("pinball_p50", "mean"),
            pinball_p90=("pinball_p90", "mean"),
            mean_pinball=("mean_pinball", "mean"),
            wis_80=("wis_80", "mean"),
            p50_mae=("p50_absolute_error", "mean"),
            scaled_squared_error=("scaled_squared_error", "mean"),
            volume=("y", "sum"),
        )
        .reset_index()
    )
    weights = per_series["volume"].to_numpy(float)
    finite_rmsse = per_series["scaled_squared_error"].notna()

    def volume_weighted(column: str) -> float | None:
        return float(np.average(per_series[column], weights=weights)) if weights.sum() > 0 else None

    actual_total = float(work["y"].sum())
    return {
        "rows": int(len(work)),
        "series": int(work["series_id"].nunique()),
        "actual_total": actual_total,
        "pinball_p10_macro_series": float(per_series["pinball_p10"].mean()),
        "pinball_p50_macro_series": float(per_series["pinball_p50"].mean()),
        "pinball_p90_macro_series": float(per_series["pinball_p90"].mean()),
        "mean_pinball_macro_series": float(per_series["mean_pinball"].mean()),
        "mean_pinball_volume_weighted_series": volume_weighted("mean_pinball"),
        "wis_80_macro_series": float(per_series["wis_80"].mean()),
        "wis_80_volume_weighted_series": volume_weighted("wis_80"),
        "empirical_coverage_80": empirical_interval_coverage(
            work["y"].to_numpy(float),
            work["p10"].to_numpy(float),
            work["p90"].to_numpy(float),
        ),
        "interval_width_80_mean": float(work["interval_width_80"].mean()),
        "p50_mae_macro_series": float(per_series["p50_mae"].mean()),
        "p50_mae_volume_weighted_series": volume_weighted("p50_mae"),
        "p50_wape": float(work["p50_absolute_error"].sum() / actual_total) if actual_total > 0 else None,
        "p50_rmsse_macro_series": (
            float(np.sqrt(per_series.loc[finite_rmsse, "scaled_squared_error"]).mean()) if finite_rmsse.any() else None
        ),
        "quantile_crossing_rate": float(work["crossed"].mean()),
        "negative_output_rate": negative_output_rate(work["p10"], work["p50"], work["p90"]),
        "supported_series_rate": float(work.groupby("series_id", observed=True)["supported"].first().mean()),
        "fallback_row_rate": float((~work["fallback_level"].isin(["none", NATIONAL_PROXY])).mean()),
    }


def _grouped_metrics(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    records = []
    for keys, part in frame.groupby(columns, sort=True, observed=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        records.append(dict(zip(columns, keys, strict=True)) | probabilistic_metric_record(part))
    return records


def summarize_probabilistic_evaluation(frame: pd.DataFrame) -> dict:
    dimensions = ["phase", "candidate", "variant", "target", "level", "aggregation_method"]
    return {
        "canonical_per_level": _grouped_metrics(frame, dimensions),
        "per_horizon": _grouped_metrics(frame, dimensions + ["horizon"]),
        "density_support_breakdown": _grouped_metrics(
            frame,
            dimensions + ["density_band", "supported"],
        ),
        "fallback_breakdown": _grouped_metrics(
            frame,
            dimensions + ["prediction_source", "fallback_level", "uncertainty_support"],
        ),
    }


def validation_retention(metrics: dict, challenger: str) -> dict:
    rows = [
        row
        for row in metrics["canonical_per_level"]
        if row["phase"] == "validation"
        and row["variant"] == RAW_VARIANT
        and row["target"] == "registrations"
        and row["level"] == "hospital"
    ]
    baseline = next(row for row in rows if row["candidate"] == BASELINE)
    model = next(row for row in rows if row["candidate"] == challenger)
    criteria = {
        "mean_pinball_improved": model["mean_pinball_macro_series"] < baseline["mean_pinball_macro_series"],
        "wis_80_improved": model["wis_80_macro_series"] < baseline["wis_80_macro_series"],
    }
    retain_challenger = all(criteria.values())
    return {
        "selection_evidence": "validation registrations at hospital/profile level only; final test excluded",
        "primary_scientific_evidence_variant": RAW_VARIANT,
        "repaired_metrics_govern_retention": False,
        "weighted_score_used": False,
        "baseline": BASELINE,
        "challenger": challenger,
        "baseline_mean_pinball": baseline["mean_pinball_macro_series"],
        "challenger_mean_pinball": model["mean_pinball_macro_series"],
        "baseline_wis_80": baseline["wis_80_macro_series"],
        "challenger_wis_80": model["wis_80_macro_series"],
        "criteria": criteria,
        "outcome": "both_retained" if retain_challenger else "quantile_lightgbm_rejected",
        "automatic_promotion": False,
    }


def quantile_extrapolation_diagnostics(
    frame: pd.DataFrame,
    threshold: float,
    example_limit: int,
) -> dict:
    long = frame.melt(
        id_vars=[
            "phase",
            "origin",
            "target",
            "level",
            "series_id",
            "horizon",
            "historical_support_max",
            "candidate",
            "variant",
        ],
        value_vars=["p10", "p50", "p90"],
        var_name="quantile",
        value_name="prediction",
    )
    support = long["historical_support_max"].to_numpy(float)
    prediction = long["prediction"].to_numpy(float)
    positive_support = support > 0
    ratio = np.full(len(long), np.nan)
    np.divide(prediction, support, out=ratio, where=positive_support)
    long["ratio"] = ratio
    long["positive_prediction_without_support"] = (~positive_support) & (prediction > 0)
    long["flagged"] = long["positive_prediction_without_support"] | (long["ratio"] > threshold)
    groups = []
    dimensions = ["phase", "candidate", "variant", "target", "level", "quantile"]
    for keys, part in long.groupby(dimensions, sort=True, observed=True):
        finite = part["ratio"].dropna()
        groups.append(
            dict(zip(dimensions, keys, strict=True))
            | {
                "cells": int(len(part)),
                "flagged_cells": int(part["flagged"].sum()),
                "flagged_series": int(part.loc[part["flagged"], "series_id"].nunique()),
                "positive_predictions_without_historical_support": int(
                    part["positive_prediction_without_support"].sum()
                ),
                "maximum_finite_ratio": float(finite.max()) if len(finite) else None,
            }
        )
    finite_examples = long[long["ratio"].notna()].nlargest(example_limit, "ratio")
    zero_examples = long[long["positive_prediction_without_support"]].nlargest(example_limit, "prediction")

    def records(rows: pd.DataFrame) -> list[dict]:
        return [
            {
                "phase": row.phase,
                "origin": str(row.origin.date()),
                "candidate": row.candidate,
                "variant": row.variant,
                "target": row.target,
                "level": row.level,
                "series_id": row.series_id,
                "horizon": int(row.horizon),
                "quantile": row.quantile,
                "historical_support_max": float(row.historical_support_max),
                "prediction": float(row.prediction),
                "ratio": None if pd.isna(row.ratio) else float(row.ratio),
            }
            for row in rows.itertuples()
        ]

    return {
        "report_only_threshold": threshold,
        "predictions_clipped_to_threshold": False,
        "by_phase_candidate_variant_target_level_quantile": groups,
        "worst_finite_ratio_examples": records(finite_examples),
        "positive_without_support_examples": records(zero_examples),
    }


def presentation_examples(
    frame: pd.DataFrame,
    challenger: str,
    source_freshness: dict,
    extrapolation_threshold: float,
) -> list[dict]:
    rows = frame[
        (frame["phase"] == "final_test")
        & (frame["candidate"] == challenger)
        & (frame["variant"] == REPAIRED_VARIANT)
        & (frame["target"] == "registrations")
        & (frame["horizon"] == 1)
    ].copy()
    selectors: Iterable[tuple[str, pd.Series]] = (
        ("directly_supported_hospital_profile", (rows["level"] == "hospital") & rows["supported"]),
        (
            "sparse_hospital_profile_explicit_fallback",
            (rows["level"] == "hospital") & ~rows["supported"],
        ),
        ("region_profile_aggregate", rows["level"] == "region"),
    )
    examples = []
    for kind, mask in selectors:
        candidates = rows[mask].sort_values(["historical_support_max", "series_id"], ascending=[False, True])
        if candidates.empty:
            raise ValueError(f"cannot build presentation example {kind}")
        row = candidates.iloc[0]
        ratio = float(row["p90"] / row["historical_support_max"]) if row["historical_support_max"] > 0 else None
        warning = bool(row["p90"] > 0) if ratio is None else bool(ratio > extrapolation_threshold)
        examples.append(
            {
                "example_kind": kind,
                "target": row["target"],
                "entity": {
                    "level": row["level"],
                    "series_id": row["series_id"],
                    "org_code": row["org_code"],
                    "region_code": row["region_code"],
                    "profile_code": row["profile_code"],
                },
                "horizon": int(row["horizon"]),
                "target_date": str(row["target_date"].date()),
                "p10": float(row["p10"]),
                "p50": float(row["p50"]),
                "p90": float(row["p90"]),
                "supported": bool(row["supported"]),
                "fallback_level": row["fallback_level"],
                "prediction_source": row["prediction_source"],
                "uncertainty_support": row["uncertainty_support"],
                "candidate": row["candidate"],
                "variant": row["variant"],
                "prediction_as_of": str(row["origin"].date()),
                "source_freshness": source_freshness,
                "extrapolation_warning": warning,
                "p90_to_historical_max_ratio": ratio,
            }
        )
    return examples
