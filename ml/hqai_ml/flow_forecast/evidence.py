from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Iterable
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from hqai_ml.features.load import SERIES_CATEGORICAL, Panel, build_rows, concat, feature_names
from hqai_ml.flow_forecast.config import FlowForecastConfig
from hqai_ml.models.config import ModelConfig
from hqai_ml.models.lgbm import encode, fit_categories
from hqai_ml.models.load_forecast import fit_target

TARGETS = ("registrations", "hospitalizations")
BASELINES = (
    "recent_value",
    "trailing_mean",
    "trailing_median",
    "seasonal_naive_t7",
    "recent_seasonal_average",
)
NATIONAL_ORG = "__national__"
NATIONAL_REGION = "__national__"
EPSILON = 1e-9


def national_panel(region: Panel) -> Panel:
    """Exact region-to-national roll-up, preserving profile membership and the dense calendar."""
    profiles = sorted(region.meta["profile_code"].unique())
    positions = {profile: np.flatnonzero(region.meta["profile_code"].to_numpy() == profile) for profile in profiles}
    meta = pd.DataFrame(
        {
            "series_id": [f"np:{profile}" for profile in profiles],
            "level": "national",
            "org_code": NATIONAL_ORG,
            "region_code": NATIONAL_REGION,
            "profile_code": profiles,
        }
    )

    def summed(values: np.ndarray) -> np.ndarray:
        return np.vstack([values[positions[profile]].sum(axis=0) for profile in profiles])

    return Panel(
        dates=region.dates,
        meta=meta,
        registrations=summed(region.registrations),
        hospitalizations=summed(region.hospitalizations),
        queue=summed(region.queue),
    )


def combine_panels(panels: Iterable[Panel]) -> Panel:
    iterator = iter(panels)
    result = next(iterator)
    for panel in iterator:
        if result.dates != panel.dates:
            raise ValueError("cannot combine panels with different calendars")
        result = concat(result, panel)
    return result


def assert_dense_observed(panel: Panel) -> None:
    """Missing calendar observations are not interchangeable with observed zero counts."""
    if not panel.dates:
        raise ValueError("panel has no dates")
    expected = [panel.dates[0] + dt.timedelta(days=offset) for offset in range(len(panel.dates))]
    if panel.dates != expected:
        raise ValueError("panel calendar has missing dates; do not impute them as zero")
    expected_shape = (len(panel.meta), len(panel.dates))
    for name in (*TARGETS, "queue"):
        values = panel.target(name) if name in TARGETS else panel.queue
        if values.shape != expected_shape:
            raise ValueError(f"{name} has shape {values.shape}, expected {expected_shape}")
        if not np.isfinite(values).all():
            raise ValueError(f"{name} contains missing or non-finite observations")
        if (values < 0).any():
            raise ValueError(f"{name} contains negative counts")


def assert_temporal_boundaries(panel: Panel, config: FlowForecastConfig) -> None:
    for origin in [*config.validation_origins, config.final_test_origin]:
        index = panel.index_of(origin)
        if index < 0 or index + config.horizon >= len(panel.dates):
            raise ValueError(f"origin {origin} does not have {config.horizon} observed target days")
    validation_end = config.validation_origins[-1] + dt.timedelta(days=config.horizon)
    test_start = config.final_test_origin + dt.timedelta(days=1)
    if validation_end >= test_start:
        raise ValueError("validation targets overlap the untouched final test")


def audit_data(
    con: duckdb.DuckDBPyConnection,
    manifest_path: Path,
    panels: dict[str, Panel],
    config: FlowForecastConfig,
) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    referral_dates = con.execute(
        """SELECT min(registration_date), max(registration_date),
                  min(hospitalization_date), max(hospitalization_date), count(*)
           FROM fact_referral"""
    ).fetchone()
    level_rows = []
    for level, panel in panels.items():
        assert_dense_observed(panel)
        for target in TARGETS:
            values = panel.target(target)
            zeros = values == 0
            per_series_zero = zeros.mean(axis=1)
            zero_heavy = per_series_zero >= config.support.zero_heavy_zero_rate
            sparse = (per_series_zero >= config.support.sparse_zero_rate) & ~zero_heavy
            dense = per_series_zero < config.support.sparse_zero_rate
            level_rows.append(
                {
                    "level": level,
                    "target": target,
                    "series": len(panel.meta),
                    "history_days": len(panel.dates),
                    "date_start": str(panel.dates[0]),
                    "date_end": str(panel.dates[-1]),
                    "observations": int(values.size),
                    "missing_dates": 0,
                    "missing_values": 0,
                    "observed_zero_rate": float(zeros.mean()),
                    "median_series_zero_rate": float(np.median(per_series_zero)),
                    "dense_series": int(dense.sum()),
                    "sparse_series": int(sparse.sum()),
                    "zero_heavy_series": int(zero_heavy.sum()),
                    "total_count": int(values.sum()),
                }
            )
    return {
        "source_manifest": "data/processed/_manifest.json",
        "ingest_window": manifest["params"] | {"dense_calendar_days": len(next(iter(panels.values())).dates)},
        "sources": manifest["sources"],
        "fact_referral": {
            "rows": int(referral_dates[4]),
            "registration_date_start": str(referral_dates[0]),
            "registration_date_end": str(referral_dates[1]),
            "hospitalization_date_start": str(referral_dates[2]),
            "hospitalization_date_end": str(referral_dates[3]),
        },
        "coverage": level_rows,
        "zero_semantics": (
            "The ingest cross-joins every observed hospital/profile key to each date in the configured window; "
            "zero is an observed no-event day. A missing date/value is an integrity error, not zero."
        ),
        "target_semantics": {
            "registrations": "daily referral registrations (operational inflow count)",
            "hospitalizations": (
                "daily cohort_hospitalization events recorded for Q1-registered referrals; not total admissions"
            ),
            "cohort_hospitalization_history_limitation": (
                "Early January is left-censored/structurally incomplete because referrals registered before "
                "2025-01-01 are absent; January is not steady-state total admission history."
            ),
            "not_estimated": ["physical beds", "occupied beds", "free beds", "bed capacity"],
        },
        "target_source": {
            "dataset": "dataset_1",
            "files": manifest["sources"]["dataset_1"]["files"],
            "aggregate_tables": ["agg_daily_hospital_profile", "agg_daily_region_profile"],
            "other_manifest_sources_used_as_targets": False,
        },
        "seasonality_claim": "No annual seasonality claim: only 90 calendar days are observed.",
    }


def baseline_arrays(
    panel: Panel,
    target: str,
    origin_index: int,
    config: FlowForecastConfig,
) -> dict[str, np.ndarray]:
    values = panel.target(target)
    horizon = config.horizon
    history = values[:, : origin_index + 1]
    mean_days = min(config.baselines.trailing_mean_days, history.shape[1])
    median_days = min(config.baselines.trailing_median_days, history.shape[1])
    output = {
        "recent_value": np.repeat(history[:, -1, None], horizon, axis=1),
        "trailing_mean": np.repeat(history[:, -mean_days:].mean(axis=1, keepdims=True), horizon, axis=1),
        "trailing_median": np.repeat(np.median(history[:, -median_days:], axis=1, keepdims=True), horizon, axis=1),
    }
    seasonal = np.empty((len(panel.meta), horizon))
    seasonal_average = np.empty_like(seasonal)
    for h in range(1, horizon + 1):
        latest = origin_index + h - 7 * math.ceil(h / 7)
        if latest < 0:
            raise ValueError("insufficient history for weekly seasonal baselines")
        seasonal[:, h - 1] = values[:, latest]
        indices = [latest - 7 * offset for offset in range(config.baselines.recent_seasonal_periods)]
        available = [index for index in indices if index >= 0]
        seasonal_average[:, h - 1] = values[:, available].mean(axis=1)
    output["seasonal_naive_t7"] = seasonal
    output["recent_seasonal_average"] = seasonal_average
    return output


def support_mask(panel: Panel, target: str, origin_index: int, config: FlowForecastConfig) -> np.ndarray:
    history_days = origin_index + 1
    if history_days < config.support.min_history_days:
        return np.zeros(len(panel.meta), dtype=bool)
    if panel.meta["level"].iloc[0] == "hospital":
        return panel.registrations[:, :history_days].mean(axis=1) >= config.support.hospital_min_mean_registrations
    if panel.meta["level"].iloc[0] == "national":
        if not config.support.national_from_region_aggregation:
            raise ValueError("national forecasts must be derived from the region aggregation")
        return np.ones(len(panel.meta), dtype=bool)
    if not config.support.region_parents_direct:
        raise ValueError("current Model C requires direct region parent series")
    return np.ones(len(panel.meta), dtype=bool)


def _add_national_aggregates(
    direct: dict[tuple[str, int], float],
    region: Panel,
    national: Panel,
    horizon: int,
) -> None:
    region_by_profile = {
        profile: region.meta.loc[region.meta["profile_code"] == profile, "series_id"].tolist()
        for profile in national.meta["profile_code"]
    }
    for row in national.meta.itertuples():
        for step in range(1, horizon + 1):
            direct[(row.series_id, step)] = float(
                sum(direct[(series_id, step)] for series_id in region_by_profile[row.profile_code])
            )


def _direct_predictions(
    panel: Panel,
    target: str,
    origin_index: int,
    model_config: ModelConfig,
) -> dict[tuple[str, int], float]:
    categories = fit_categories(panel.meta, SERIES_CATEGORICAL)
    booster = fit_target(panel, target, origin_index, categories, model_config)
    lf = model_config.load_forecast
    rows = build_rows(
        panel,
        target,
        [origin_index],
        lf.horizon,
        lf.lags,
        lf.rolling,
        set(lf.holidays),
        max_target_index=None,
    )
    features = feature_names(lf.lags, lf.rolling)
    predictions = booster.predict(encode(rows, features, categories))
    if (predictions < 0).any():
        raise ValueError("Poisson LightGBM emitted a negative operational count")
    return {
        (str(series_id), int(horizon)): float(prediction)
        for series_id, horizon, prediction in zip(rows["series_id"], rows["horizon"], predictions, strict=True)
    }


def _history_metadata(panel: Panel, target: str, origin_index: int, config: FlowForecastConfig) -> pd.DataFrame:
    history = panel.target(target)[:, : origin_index + 1]
    zero_rate = (history == 0).mean(axis=1)
    diffs = np.diff(history, axis=1)
    scale = np.mean(diffs**2, axis=1) if diffs.shape[1] else np.zeros(len(panel.meta))
    density = np.where(
        zero_rate >= config.support.zero_heavy_zero_rate,
        "zero_heavy",
        np.where(zero_rate >= config.support.sparse_zero_rate, "sparse", "dense"),
    )
    out = panel.meta.copy()
    out["zero_rate"] = zero_rate
    out["density_band"] = density
    out["rmsse_scale"] = scale
    out["historical_support_max"] = history.max(axis=1)
    return out


def _fallback_predictions(
    all_panel: Panel,
    direct: dict[tuple[str, int], float],
    supported: dict[str, bool],
    target: str,
    origin_index: int,
    config: FlowForecastConfig,
) -> tuple[dict[tuple[str, int], float], dict[str, str]]:
    meta = all_panel.meta.set_index("series_id", drop=False)
    values = all_panel.target(target)
    position = {series_id: index for index, series_id in enumerate(all_panel.meta["series_id"])}
    region_id = {
        (row.region_code, row.profile_code): row.series_id
        for row in all_panel.meta.itertuples()
        if row.level == "region"
    }
    national_id = {row.profile_code: row.series_id for row in all_panel.meta.itertuples() if row.level == "national"}
    seasonal = baseline_arrays(all_panel, target, origin_index, config)["recent_seasonal_average"]
    history_total = values[:, : origin_index + 1].sum(axis=1)
    predictions = dict(direct)
    fallback: dict[str, str] = {}

    def parent(series_id: str) -> str | None:
        row = meta.loc[series_id]
        if row["level"] == "hospital":
            return region_id.get((row["region_code"], row["profile_code"]))
        if row["level"] == "region":
            return national_id.get(row["profile_code"])
        return None

    ordered = pd.concat(
        [all_panel.meta[all_panel.meta["level"] == level] for level in ("national", "region", "hospital")],
        ignore_index=True,
    )
    for row in ordered.itertuples():
        series_id = row.series_id
        if supported[series_id]:
            fallback[series_id] = "direct_model"
            continue
        parent_id = parent(series_id)
        child_index = position[series_id]
        if parent_id is not None:
            parent_index = position[parent_id]
            denominator = history_total[parent_index]
            if denominator > 0:
                share = float(history_total[child_index] / denominator)
                for horizon in range(1, config.horizon + 1):
                    predictions[(series_id, horizon)] = predictions[(parent_id, horizon)] * share
                fallback[series_id] = f"{meta.loc[parent_id, 'level']}_profile_share"
                continue
        for horizon in range(1, config.horizon + 1):
            predictions[(series_id, horizon)] = float(seasonal[child_index, horizon - 1])
        fallback[series_id] = "own_history_zero" if history_total[child_index] == 0 else "own_history_seasonal"
    return predictions, fallback


def evaluate_origin(
    panels: dict[str, Panel],
    origin: dt.date,
    phase: str,
    config: FlowForecastConfig,
    model_config: ModelConfig,
) -> pd.DataFrame:
    all_panel = combine_panels(panels.values())
    origin_index = all_panel.index_of(origin)
    frames = []
    for target in TARGETS:
        masks = {level: support_mask(panel, target, origin_index, config) for level, panel in panels.items()}
        supported_panels = [
            panel.subset(masks[level]) for level, panel in panels.items() if level != "national" and masks[level].any()
        ]
        direct_panel = combine_panels(supported_panels)
        direct = _direct_predictions(direct_panel, target, origin_index, model_config)
        _add_national_aggregates(direct, panels["region"], panels["national"], config.horizon)
        supported = {
            series_id: bool(flag)
            for level, panel in panels.items()
            for series_id, flag in zip(panel.meta["series_id"], masks[level], strict=True)
        }
        model_predictions, fallback = _fallback_predictions(all_panel, direct, supported, target, origin_index, config)
        for series_id in panels["national"].meta["series_id"]:
            fallback[series_id] = "region_aggregate"
        baselines = baseline_arrays(all_panel, target, origin_index, config)
        history_meta = _history_metadata(all_panel, target, origin_index, config)
        actual = all_panel.target(target)[:, origin_index + 1 : origin_index + config.horizon + 1]
        repeated_meta = history_meta.loc[history_meta.index.repeat(config.horizon)].reset_index(drop=True)
        repeated_meta["horizon"] = np.tile(np.arange(1, config.horizon + 1), len(all_panel.meta))
        repeated_meta["target_date"] = [
            origin + dt.timedelta(days=int(horizon)) for horizon in repeated_meta["horizon"]
        ]
        repeated_meta["y"] = actual.reshape(-1)
        repeated_meta["target"] = target
        repeated_meta["origin"] = origin
        repeated_meta["phase"] = phase
        repeated_meta["supported"] = repeated_meta["series_id"].map(supported)
        for candidate in (*BASELINES, config.challenger.id):
            part = repeated_meta.copy()
            part["candidate"] = candidate
            if candidate == config.challenger.id:
                part["prediction"] = [
                    model_predictions[(series_id, int(horizon))]
                    for series_id, horizon in zip(part["series_id"], part["horizon"], strict=True)
                ]
                part["fallback_level"] = part["series_id"].map(fallback)
            else:
                part["prediction"] = baselines[candidate].reshape(-1)
                part["fallback_level"] = np.where(part["supported"], "direct_history", "unsupported_own_history")
            frames.append(part)
    result = pd.concat(frames, ignore_index=True)
    for column in (
        "series_id",
        "level",
        "org_code",
        "region_code",
        "profile_code",
        "density_band",
        "target",
        "phase",
        "candidate",
        "fallback_level",
    ):
        result[column] = result[column].astype("category")
    result["origin"] = pd.to_datetime(result["origin"])
    result["target_date"] = pd.to_datetime(result["target_date"])
    result["horizon"] = result["horizon"].astype("int16")
    return result


def poisson_deviance(y: np.ndarray, prediction: np.ndarray) -> np.ndarray:
    prediction = np.maximum(prediction, EPSILON)
    term = np.zeros_like(y, dtype=float)
    positive = y > 0
    term[positive] = y[positive] * np.log(y[positive] / prediction[positive])
    return 2.0 * (term - (y - prediction))


def metric_record(frame: pd.DataFrame) -> dict:
    if frame.empty:
        raise ValueError("cannot score an empty evaluation frame")
    work = frame.copy()
    work["absolute_error"] = np.abs(work["y"] - work["prediction"])
    work["poisson_deviance"] = poisson_deviance(work["y"].to_numpy(float), work["prediction"].to_numpy(float))
    work["scaled_squared_error"] = np.where(
        work["rmsse_scale"] > 0,
        (work["y"] - work["prediction"]) ** 2 / work["rmsse_scale"],
        np.nan,
    )
    per_series = (
        work.groupby("series_id", sort=False)
        .agg(
            mae=("absolute_error", "mean"),
            volume=("y", "sum"),
            poisson_deviance=("poisson_deviance", "mean"),
            scaled_squared_error=("scaled_squared_error", "mean"),
        )
        .reset_index()
    )
    finite_rmsse = per_series["scaled_squared_error"].notna()
    weights = per_series["volume"].to_numpy(float)
    return {
        "rows": int(len(work)),
        "series": int(work["series_id"].nunique()),
        "actual_total": float(work["y"].sum()),
        "mae_macro_series": float(per_series["mae"].mean()),
        "mae_volume_weighted_series": (
            float(np.average(per_series["mae"], weights=weights)) if weights.sum() > 0 else None
        ),
        "wape": float(work["absolute_error"].sum() / work["y"].sum()) if work["y"].sum() > 0 else None,
        "rmsse_macro_series": (
            float(np.sqrt(per_series.loc[finite_rmsse, "scaled_squared_error"]).mean()) if finite_rmsse.any() else None
        ),
        "rmsse_supported_series": int(finite_rmsse.sum()),
        "poisson_deviance_macro_series": float(per_series["poisson_deviance"].mean()),
        "poisson_deviance_pooled": float(work["poisson_deviance"].mean()),
        "supported_series": int(work.loc[work["supported"], "series_id"].nunique()),
        "supported_series_rate": float(work.groupby("series_id")["supported"].first().mean()),
        "fallback_row_rate": float(
            (~work["fallback_level"].isin(["direct_model", "direct_history", "region_aggregate"])).mean()
        ),
    }


def grouped_metrics(frame: pd.DataFrame, columns: list[str]) -> list[dict]:
    records = []
    for keys, part in frame.groupby(columns, sort=True, observed=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        records.append(dict(zip(columns, keys, strict=True)) | metric_record(part))
    return records


def summarize_evaluation(frame: pd.DataFrame) -> dict:
    return {
        "canonical_per_level": grouped_metrics(frame, ["phase", "candidate", "target", "level"]),
        "per_horizon": grouped_metrics(frame, ["phase", "candidate", "target", "level", "horizon"]),
        "hospital_region_breakdown": grouped_metrics(
            frame[frame["level"] == "hospital"],
            ["phase", "candidate", "target", "region_code"],
        ),
        "density_breakdown": grouped_metrics(frame, ["phase", "candidate", "target", "level", "density_band"]),
        "fallback_coverage": [
            {
                "phase": phase,
                "candidate": candidate,
                "target": target,
                "level": level,
                "fallback_level": fallback_level,
                "rows": int(len(part)),
                "series": int(part["series_id"].nunique()),
                "actual_total": float(part["y"].sum()),
            }
            for (phase, candidate, target, level, fallback_level), part in frame.groupby(
                ["phase", "candidate", "target", "level", "fallback_level"],
                sort=True,
                observed=True,
            )
        ],
    }


def hierarchy_diagnostics(panels: dict[str, Panel]) -> dict:
    hospital, region, national = (panels[level] for level in ("hospital", "region", "national"))
    region_keys = set(zip(region.meta["region_code"], region.meta["profile_code"], strict=True))
    national_profiles = set(national.meta["profile_code"])
    checks = {}
    for target in TARGETS:
        hospital_values = hospital.target(target)
        region_values = region.target(target)
        national_values = national.target(target)
        hospital_rollup = {
            key: hospital_values[
                (hospital.meta["region_code"].to_numpy() == key[0])
                & (hospital.meta["profile_code"].to_numpy() == key[1])
            ].sum(axis=0)
            for key in region_keys
        }
        region_consistent = all(
            np.array_equal(hospital_rollup[key], region_values[index])
            for index, key in enumerate(zip(region.meta["region_code"], region.meta["profile_code"], strict=True))
        )
        national_consistent = all(
            np.array_equal(
                region_values[region.meta["profile_code"].to_numpy() == profile].sum(axis=0),
                national_values[index],
            )
            for index, profile in enumerate(national.meta["profile_code"])
        )
        checks[target] = {
            "hospital_to_region_exact": region_consistent,
            "region_to_national_exact": national_consistent,
            "max_hospital_to_region_absolute_difference": float(
                max(
                    np.max(np.abs(hospital_rollup[key] - region_values[index]))
                    for index, key in enumerate(
                        zip(region.meta["region_code"], region.meta["profile_code"], strict=True)
                    )
                )
            ),
        }
    return {
        "hospital_profile_series": len(hospital.meta),
        "hospital_series_with_region_profile_parent": sum(
            (region_code, profile_code) in region_keys
            for region_code, profile_code in zip(
                hospital.meta["region_code"], hospital.meta["profile_code"], strict=True
            )
        ),
        "region_profile_series": len(region.meta),
        "region_series_with_national_profile_parent": sum(
            profile in national_profiles for profile in region.meta["profile_code"]
        ),
        "national_profile_series": len(national.meta),
        "data_rollups_exact": bool(
            all(item["hospital_to_region_exact"] and item["region_to_national_exact"] for item in checks.values())
        ),
        "aggregation_checks": checks,
        "hospital_to_region_forecast_reconciliation_applied": False,
        "national_forecast_method": "exact sum of region/profile forecasts",
    }


def validation_recommendation(metrics: dict, challenger: str) -> dict:
    validation = [row for row in metrics["canonical_per_level"] if row["phase"] == "validation"]
    comparisons = []
    challenger_wins = 0
    for target in sorted({row["target"] for row in validation}):
        for level in ("hospital", "region", "national"):
            cell = [row for row in validation if row["target"] == target and row["level"] == level]
            model = next(row for row in cell if row["candidate"] == challenger)
            baseline = min(
                (row for row in cell if row["candidate"] != challenger),
                key=lambda row: row["wape"],
            )
            beats = model["wape"] < baseline["wape"]
            challenger_wins += int(beats)
            comparisons.append(
                {
                    "target": target,
                    "level": level,
                    "candidate_wape": model["wape"],
                    "strongest_baseline": baseline["candidate"],
                    "strongest_baseline_wape": baseline["wape"],
                    "candidate_beats_baseline": beats,
                }
            )
    total = len(comparisons)
    losses = total - challenger_wins
    return {
        "promotion": "do_not_promote",
        "selection_evidence": "validation only; final test excluded",
        "primary_comparison": "WAPE within each target and hierarchy level",
        "candidate_level_target_wins": challenger_wins,
        "candidate_level_target_losses": losses,
        "comparisons": comparisons,
        "reason": (
            f"Validation-only WAPE: {challenger} beat the strongest eligible baseline in "
            f"{challenger_wins}/{total} target-level cells and lost {losses}/{total}; retain evidence "
            "without promotion because performance is not uniformly superior and history is only 90 days."
        ),
        "automatic_promotion": False,
    }


def extrapolation_diagnostics(
    frame: pd.DataFrame,
    challenger: str,
    threshold: float,
    example_limit: int,
) -> dict:
    model = frame[frame["candidate"] == challenger].copy()
    support = model["historical_support_max"].to_numpy(float)
    prediction = model["prediction"].to_numpy(float)
    positive_support = support > 0
    ratio = np.full_like(prediction, np.nan)
    np.divide(prediction, support, out=ratio, where=positive_support)
    model["extrapolation_ratio"] = ratio
    model["positive_prediction_without_support"] = (~positive_support) & (prediction > 0)
    model["extrapolation_flag"] = model["positive_prediction_without_support"] | (
        model["extrapolation_ratio"] > threshold
    )
    groups = []
    for (phase, target, level), part in model.groupby(["phase", "target", "level"], observed=True, sort=True):
        finite = part["extrapolation_ratio"].dropna()
        groups.append(
            {
                "phase": phase,
                "target": target,
                "level": level,
                "cells": int(len(part)),
                "flagged_cells": int(part["extrapolation_flag"].sum()),
                "flagged_series": int(part.loc[part["extrapolation_flag"], "series_id"].nunique()),
                "positive_predictions_without_historical_support": int(
                    part["positive_prediction_without_support"].sum()
                ),
                "maximum_finite_ratio": float(finite.max()) if len(finite) else None,
            }
        )

    def examples(rows: pd.DataFrame) -> list[dict]:
        return [
            {
                "phase": row.phase,
                "origin": str(row.origin.date()),
                "target": row.target,
                "level": row.level,
                "series_id": row.series_id,
                "horizon": int(row.horizon),
                "historical_support_max": float(row.historical_support_max),
                "prediction": float(row.prediction),
                "ratio": (
                    "infinite_no_positive_history"
                    if row.positive_prediction_without_support
                    else float(row.extrapolation_ratio)
                ),
            }
            for row in rows.itertuples()
        ]

    no_support = model[model["positive_prediction_without_support"]].nlargest(example_limit, "prediction")
    finite_flags = model[model["extrapolation_flag"] & ~model["positive_prediction_without_support"]].nlargest(
        example_limit, "extrapolation_ratio"
    )
    worst_finite = model[model["extrapolation_ratio"].notna()].nlargest(example_limit, "extrapolation_ratio")
    tracked = model[model["series_id"] == "rp:75:DH"].copy()
    tracked_ratio = tracked["extrapolation_ratio"].dropna()
    return {
        "report_only_threshold": threshold,
        "predictions_clipped_to_threshold": False,
        "by_phase_target_level": groups,
        "positive_without_support_examples": examples(no_support),
        "threshold_exceedance_examples": examples(finite_flags),
        "worst_finite_ratio_examples": examples(worst_finite),
        "tracked_rp_75_DH": {
            "present": not tracked.empty,
            "maximum_finite_ratio": float(tracked_ratio.max()) if len(tracked_ratio) else None,
            "maximum_prediction": float(tracked["prediction"].max()) if len(tracked) else None,
            "flagged_cells": int(tracked["extrapolation_flag"].sum()),
        },
    }


def forecast_hierarchy_diagnostics(frame: pd.DataFrame, challenger: str) -> dict:
    model = frame[frame["candidate"] == challenger]
    hospital = model[model["level"] == "hospital"]
    region = model[model["level"] == "region"]
    national = model[model["level"] == "national"]
    keys = ["phase", "origin", "target", "horizon", "region_code", "profile_code"]
    hospital_sum = hospital.groupby(keys, observed=True)["prediction"].sum().rename("child_sum")
    region_values = region.set_index(keys)["prediction"].rename("parent")
    hospital_region = region_values.to_frame().join(hospital_sum, how="left").fillna({"child_sum": 0.0})
    hospital_region["absolute_difference"] = np.abs(hospital_region["parent"] - hospital_region["child_sum"])

    national_keys = ["phase", "origin", "target", "horizon", "profile_code"]
    region_sum = region.groupby(national_keys, observed=True)["prediction"].sum().rename("child_sum")
    national_values = national.set_index(national_keys)["prediction"].rename("parent")
    region_national = national_values.to_frame().join(region_sum, how="left").fillna({"child_sum": 0.0})
    region_national["absolute_difference"] = np.abs(region_national["parent"] - region_national["child_sum"])
    return {
        "hospital_to_region": {
            "cells": int(len(hospital_region)),
            "exact_cells": int((hospital_region["absolute_difference"] <= EPSILON).sum()),
            "max_absolute_difference": float(hospital_region["absolute_difference"].max()),
            "mean_absolute_difference": float(hospital_region["absolute_difference"].mean()),
            "reconciled": False,
        },
        "region_to_national": {
            "cells": int(len(region_national)),
            "exact_cells": int((region_national["absolute_difference"] <= EPSILON).sum()),
            "max_absolute_difference": float(region_national["absolute_difference"].max()),
            "mean_absolute_difference": float(region_national["absolute_difference"].mean()),
            "method": "national forecast is the exact region sum",
        },
    }
