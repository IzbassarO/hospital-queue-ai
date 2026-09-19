"""Central-only hierarchy and deterministic fallback evaluation for saved flow forecasts."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from hqai_ml.features.load import Panel
from hqai_ml.flow_forecast.config import FlowHierarchyConfig, FlowQuantileConfig
from hqai_ml.flow_forecast.evidence import baseline_arrays
from hqai_ml.flow_forecast.quantile import INTERNAL_TARGETS, NATIONAL_PROXY
from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun

CURRENT_FALLBACK = "current_region_profile_share"
BLENDED_FALLBACK = "support_weighted_parent_own_blend"
CURRENT_DIRECT = "current_direct"
BOTTOM_UP = "bottom_up_hospital"
PARENT_SCALING = "parent_consistent_region_scaling"
EPSILON = 1e-9
HOSPITAL_REGION_KEYS = ["phase", "origin", "target", "horizon", "region_code", "profile_code"]
REGION_NATIONAL_KEYS = ["phase", "origin", "target", "horizon", "profile_code"]


def calibration_source_origin_key(origin: dt.date, phase: str, version: str) -> CheckpointKey:
    return CheckpointKey(
        "load_forecast",
        candidate_id="flow-temporal-calibration",
        trial_id=version,
        fold_id=phase,
        forecast_origin=origin.isoformat(),
    )


def load_verified_calibration_intervals(
    artifacts_dir: Path,
    calibration_run_id: str,
    source_run_id: str,
    source_scientific_identity: str,
    source_artifact_identity: str,
    phases: list[tuple[dt.date, str]],
    method: str,
) -> tuple[pd.DataFrame, dict]:
    """Read immutable level-local calibration artifacts and verify their quantile-source lineage."""
    run = ExperimentRun.read_only(artifacts_dir, calibration_run_id)
    if run.manifest["status"] != "completed":
        raise ValueError(f"calibration run {calibration_run_id!r} is not completed")
    hyperparameters = run.manifest["hyperparameters"]
    source = hyperparameters["source_run"]
    expected = {
        "run_id": source_run_id,
        "scientific_identity": source_scientific_identity,
        "artifact_identity": source_artifact_identity,
    }
    mismatches = [key for key, value in expected.items() if source.get(key) != value]
    if mismatches:
        raise ValueError(f"calibration source lineage is incompatible: {mismatches}")
    version = hyperparameters["calibration_version"]
    calibration = hyperparameters["calibration"]
    if method not in calibration["methods"]:
        raise ValueError(f"calibration method {method!r} is absent from the accepted run")
    parameters = {
        "calibration_version": version,
        "source_artifact_identity": source_artifact_identity,
        "methods": calibration["methods"],
        "source_variant": calibration["source_variant"],
    }
    frames = []
    artifacts = []
    for origin, phase in phases:
        key = calibration_source_origin_key(origin, phase, version)
        checkpoint = run.reusable_checkpoint(key, parameters=parameters)
        if checkpoint is None or checkpoint["evaluation"]["status"] != "completed":
            raise ValueError(f"calibration origin checkpoint is incomplete: {phase} {origin}")
        artifact = artifacts_dir / checkpoint["artifact"]["path"]
        metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
        resources = metadata["resources"]
        if resources["origin"] != str(origin) or resources["phase"] != phase:
            raise ValueError(f"calibration origin metadata mismatch: {phase} {origin}")
        frame = pd.read_parquet(artifact / "calibrated-evaluation.parquet")
        selected = frame[frame["calibration_method"] == method].copy()
        if selected.empty:
            raise ValueError(f"calibration origin has no {method!r} rows: {phase} {origin}")
        if set(pd.to_datetime(selected["origin"]).dt.date) != {origin} or set(selected["phase"]) != {phase}:
            raise ValueError(f"calibration row identity mismatch: {phase} {origin}")
        frames.append(selected)
        artifacts.append(
            {
                "origin": str(origin),
                "phase": phase,
                "checkpoint_identity": checkpoint["scientific_identity_sha256"],
                "artifact_path": checkpoint["artifact"]["path"],
                "artifact_sha256": checkpoint["artifact"]["sha256"],
            }
        )
    return pd.concat(frames, ignore_index=True), {
        "calibration_run_id": calibration_run_id,
        "calibration_scientific_identity": run.manifest["scientific_identity_sha256"],
        "calibration_version": version,
        "source_run_id": source_run_id,
        "source_scientific_identity": source_scientific_identity,
        "source_artifact_identity": source_artifact_identity,
        "method": method,
        "origin_artifacts": artifacts,
    }


def build_own_history_signals(
    hospital: Panel,
    origins: list[dt.date],
    targets: list[str],
    quantile_config: FlowQuantileConfig,
) -> pd.DataFrame:
    """Build origin-legal own-history evidence without fitting or regenerating a forecast model."""
    records = []
    for origin in origins:
        origin_index = hospital.index_of(origin)
        for public_target in targets:
            target = INTERNAL_TARGETS[public_target]
            values = hospital.target(target)
            history = values[:, : origin_index + 1]
            seasonal = baseline_arrays(hospital, target, origin_index, quantile_config)["recent_seasonal_average"]
            repeated = hospital.meta[["series_id"]].loc[hospital.meta.index.repeat(quantile_config.horizon)].copy()
            repeated["origin"] = pd.Timestamp(origin)
            repeated["target"] = public_target
            repeated["horizon"] = np.tile(np.arange(1, quantile_config.horizon + 1), len(hospital.meta))
            repeated["own_recent_seasonal"] = seasonal.reshape(-1)
            repeated["history_total"] = np.repeat(history.sum(axis=1), quantile_config.horizon)
            repeated["history_nonzero_days"] = np.repeat((history > 0).sum(axis=1), quantile_config.horizon)
            repeated["history_days"] = history.shape[1]
            records.append(repeated)
    return pd.concat(records, ignore_index=True)


def fallback_forecast_values(frame: pd.DataFrame, config: FlowHierarchyConfig) -> dict[str, np.ndarray]:
    current = frame["source_central_value"].to_numpy(float, copy=True)
    blended = current.copy()
    eligible = (
        (frame["level"] == "hospital")
        & (frame["fallback_level"] == "region_profile_share")
        & (frame["history_total"].fillna(0) > 0)
    )
    nonzero_days = frame["history_nonzero_days"].fillna(0).to_numpy(float)
    weight = np.minimum(
        config.fallback.maximum_own_weight,
        config.fallback.maximum_own_weight * nonzero_days / config.fallback.full_own_weight_nonzero_days,
    )
    own = frame["own_recent_seasonal"].fillna(0).to_numpy(float)
    mask = eligible.to_numpy()
    blended[mask] = weight[mask] * own[mask] + (1.0 - weight[mask]) * current[mask]
    no_history = (frame["level"] == "hospital") & (frame["history_total"].fillna(0) <= 0)
    if not np.array_equal(blended[no_history], current[no_history]):
        raise ValueError("fallback challenger cannot fabricate forecasts for no-history series")
    return {CURRENT_FALLBACK: current, BLENDED_FALLBACK: blended}


def central_metric_record(frame: pd.DataFrame, forecast: np.ndarray) -> dict:
    work = frame[["series_id", "y", "rmsse_scale"]].copy()
    work["forecast"] = np.asarray(forecast, dtype=float)
    work["absolute_error"] = np.abs(work["y"] - work["forecast"])
    scale = work["rmsse_scale"].to_numpy(float)
    squared_scaled = np.full(len(work), np.nan)
    np.divide(
        (work["y"].to_numpy(float) - work["forecast"].to_numpy(float)) ** 2,
        scale,
        out=squared_scaled,
        where=scale > 0,
    )
    work["scaled_squared_error"] = squared_scaled
    per_series = (
        work.groupby("series_id", sort=False, observed=True)
        .agg(mae=("absolute_error", "mean"), scaled_squared_error=("scaled_squared_error", "mean"))
        .reset_index()
    )
    finite = per_series["scaled_squared_error"].notna()
    actual_total = float(work["y"].sum())
    return {
        "rows": int(len(work)),
        "series": int(work["series_id"].nunique()),
        "actual_total": actual_total,
        "wape": float(work["absolute_error"].sum() / actual_total) if actual_total > 0 else None,
        "mae_macro_series": float(per_series["mae"].mean()),
        "rmsse_macro_series": (
            float(np.sqrt(per_series.loc[finite, "scaled_squared_error"]).mean()) if finite.any() else None
        ),
        "rmsse_supported_series": int(finite.sum()),
    }


def _values_by_key(frame: pd.DataFrame, values: np.ndarray, keys: list[str]) -> dict[tuple, float]:
    work = frame[keys].copy()
    work["forecast"] = values
    if work.duplicated(keys).any():
        raise ValueError(f"forecast rows are not unique for hierarchy keys {keys}")
    return {tuple(row[:-1]): float(row[-1]) for row in work.itertuples(index=False, name=None)}


def _map_values(frame: pd.DataFrame, keys: list[str], mapping: dict[tuple, float]) -> np.ndarray:
    result = [mapping.get(tuple(row)) for row in frame[keys].itertuples(index=False, name=None)]
    if any(value is None for value in result):
        raise ValueError(f"hierarchy has missing parent values for keys {keys}")
    return np.asarray(result, dtype=float)


def reconcile_central(
    frame: pd.DataFrame,
    base_values: np.ndarray,
    alternative: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return central values, forecast-source labels and hierarchy-status labels."""
    base = np.asarray(base_values, dtype=float)
    if (base < -EPSILON).any():
        raise ValueError("operational central source must be non-negative before reconciliation")
    values = base.copy()
    source = frame["base_forecast_source"].astype(str).to_numpy(copy=True)
    status = np.full(len(frame), "unreconciled", dtype=object)
    if alternative == CURRENT_DIRECT:
        return values, source, status

    hospital_mask = (frame["level"] == "hospital").to_numpy()
    region_mask = (frame["level"] == "region").to_numpy()
    national_mask = (frame["level"] == "national").to_numpy()
    hospital = frame.loc[hospital_mask]
    region = frame.loc[region_mask]

    if alternative == BOTTOM_UP:
        hospital_sum = (
            hospital.assign(_forecast=base[hospital_mask])
            .groupby(HOSPITAL_REGION_KEYS, sort=False, observed=True)["_forecast"]
            .sum()
            .to_dict()
        )
        values[region_mask] = _map_values(region, HOSPITAL_REGION_KEYS, hospital_sum)
        source[region_mask] = "bottom_up_hospital_sum"
        status[region_mask] = "bottom_up_exact"
        status[hospital_mask] = "bottom_up_child_unchanged"
    elif alternative == PARENT_SCALING:
        parent_values = _values_by_key(region, base[region_mask], HOSPITAL_REGION_KEYS)
        parent = _map_values(hospital, HOSPITAL_REGION_KEYS, parent_values)
        child_frame = hospital[HOSPITAL_REGION_KEYS].copy()
        child_frame["_base"] = base[hospital_mask]
        child_sum = child_frame.groupby(HOSPITAL_REGION_KEYS, sort=False, observed=True)["_base"].transform("sum")
        child_sum_values = child_sum.to_numpy(float)
        scaled = np.zeros(len(hospital), dtype=float)
        ordinary = child_sum_values > EPSILON
        scaled[ordinary] = base[hospital_mask][ordinary] * parent[ordinary] / child_sum_values[ordinary]
        allocation = (~ordinary) & (parent > EPSILON)
        if allocation.any():
            weights = hospital["history_total"].fillna(0).to_numpy(float)
            weight_frame = hospital[HOSPITAL_REGION_KEYS].copy()
            weight_frame["_weight"] = weights
            weight_sum = weight_frame.groupby(HOSPITAL_REGION_KEYS, sort=False, observed=True)["_weight"].transform(
                "sum"
            )
            weight_sum_values = weight_sum.to_numpy(float)
            if (weight_sum_values[allocation] <= EPSILON).any():
                raise ValueError("positive parent with zero child forecast has no historical support for allocation")
            scaled[allocation] = parent[allocation] * weights[allocation] / weight_sum_values[allocation]
        values[hospital_mask] = scaled
        source[hospital_mask] = "parent_consistent_scaled_child"
        status[hospital_mask] = "parent_scaled_to_region"
        source[region_mask] = "accepted_region_central_anchor"
        status[region_mask] = "region_anchor"
    else:
        raise ValueError(f"unknown hierarchy alternative {alternative!r}")

    region_sum = (
        region.assign(_forecast=values[region_mask])
        .groupby(REGION_NATIONAL_KEYS, sort=False, observed=True)["_forecast"]
        .sum()
        .to_dict()
    )
    values[national_mask] = _map_values(frame.loc[national_mask], REGION_NATIONAL_KEYS, region_sum)
    source[national_mask] = "exact_region_central_sum"
    status[national_mask] = "exact_region_sum"
    return values, source, status


def coherence_metrics(frame: pd.DataFrame, forecast: np.ndarray, tolerance: float) -> list[dict]:
    work = frame.copy()
    work["_forecast"] = np.asarray(forecast, dtype=float)
    records = []
    for keys, parent_level, child_level, name in (
        (HOSPITAL_REGION_KEYS, "region", "hospital", "hospital_to_region"),
        (REGION_NATIONAL_KEYS, "national", "region", "region_to_national"),
    ):
        child = work[work["level"] == child_level].groupby(keys, sort=False, observed=True)["_forecast"].sum()
        parent = work[work["level"] == parent_level].set_index(keys)["_forecast"]
        joined = parent.rename("parent").to_frame().join(child.rename("child_sum"), how="left").fillna(0.0)
        difference = np.abs(joined["parent"] - joined["child_sum"])
        denominator = float(np.abs(joined["parent"]).sum())
        records.append(
            {
                "boundary": name,
                "cells": int(len(joined)),
                "exact_cells": int((difference <= tolerance).sum()),
                "mean_absolute_error": float(difference.mean()),
                "max_absolute_error": float(difference.max()),
                "absolute_error_ratio": float(difference.sum() / denominator) if denominator > 0 else None,
                "exact_within_tolerance": bool((difference <= tolerance).all()),
            }
        )
    return records


def materially_changed(base: np.ndarray, candidate: np.ndarray, config: FlowHierarchyConfig) -> np.ndarray:
    absolute = np.abs(np.asarray(candidate) - np.asarray(base))
    relative = absolute / np.maximum(np.abs(np.asarray(base)), EPSILON)
    return (absolute > config.material_change_absolute) & (relative > config.material_change_relative)


def _rank_value(value: float | None) -> float:
    return float(value) if value is not None and np.isfinite(value) else float("inf")


def select_fallback(metrics: list[dict]) -> dict:
    eligible = [
        row
        for row in metrics
        if row["phase"] == "validation" and row["target"] == "registrations" and row["scope"] == "affected"
    ]
    if not eligible:
        return {
            "selected": CURRENT_FALLBACK,
            "reason": "no validation registration rows used the regional fallback",
            "final_test_used_for_selection": False,
        }
    selected = min(
        eligible,
        key=lambda row: (
            _rank_value(row["wape"]),
            _rank_value(row["mae_macro_series"]),
            _rank_value(row["rmsse_macro_series"]),
            row["fallback_candidate"] != CURRENT_FALLBACK,
        ),
    )
    return {
        "selected": selected["fallback_candidate"],
        "selection_evidence": "validation registrations, affected hospital/profile rows only",
        "ordered_metrics": ["wape", "mae_macro_series", "rmsse_macro_series"],
        "selected_metrics": {key: selected[key] for key in ("wape", "mae_macro_series", "rmsse_macro_series")},
        "final_test_used_for_selection": False,
    }


def select_hierarchy(metrics: list[dict], coherence: list[dict], tolerance: float) -> dict:
    validation_coherence = [row for row in coherence if row["phase"] == "validation"]
    eligibility = {
        alternative: all(
            row["exact_within_tolerance"] for row in validation_coherence if row["hierarchy_alternative"] == alternative
        )
        for alternative in sorted({row["hierarchy_alternative"] for row in validation_coherence})
    }
    eligible = [alternative for alternative, allowed in eligibility.items() if allowed]
    if not eligible:
        raise ValueError(f"no hierarchy alternative is coherent within tolerance {tolerance}")
    validation = [row for row in metrics if row["phase"] == "validation" and row["target"] == "registrations"]

    def metric(alternative: str, level: str, name: str) -> float:
        row = next(row for row in validation if row["hierarchy_alternative"] == alternative and row["level"] == level)
        return _rank_value(row[name])

    selected = min(
        eligible,
        key=lambda alternative: (
            metric(alternative, "hospital", "wape"),
            metric(alternative, "region", "wape"),
            metric(alternative, "national", "wape"),
            metric(alternative, "hospital", "mae_macro_series"),
            metric(alternative, "hospital", "rmsse_macro_series"),
            alternative,
        ),
    )
    return {
        "selected": selected,
        "eligibility": eligibility,
        "coherence_tolerance": tolerance,
        "selection_evidence": "validation registrations only after validation-only fallback selection",
        "ordered_metrics": [
            "hospital_wape",
            "region_wape",
            "national_wape",
            "hospital_mae_macro_series",
            "hospital_rmsse_macro_series",
        ],
        "final_test_used_for_selection": False,
    }


def evaluate_hierarchy(frame: pd.DataFrame, config: FlowHierarchyConfig) -> tuple[pd.DataFrame, dict]:
    required = {
        "phase",
        "origin",
        "target",
        "level",
        "series_id",
        "region_code",
        "profile_code",
        "horizon",
        "y",
        "rmsse_scale",
        "supported",
        "fallback_level",
        "prediction_source",
        "source_central_value",
        "raw_p10",
        "raw_p50",
        "raw_p90",
        "history_total",
        "history_nonzero_days",
        "own_recent_seasonal",
        "calibration_status",
        "calibration_version",
        "uncertainty_support",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"hierarchy source is missing columns: {sorted(missing)}")
    work = frame.copy()
    raw_before = work[["raw_p10", "raw_p50", "raw_p90"]].to_numpy(copy=True)
    fallback_values = fallback_forecast_values(work, config)
    fallback_metrics = []
    affected = (work["level"] == "hospital") & (work["fallback_level"] == "region_profile_share")
    for fallback_candidate, values in fallback_values.items():
        for phase in ("validation", "final_test"):
            for target in config.targets:
                for scope, scope_mask in (("all_hospital", work["level"] == "hospital"), ("affected", affected)):
                    mask = (work["phase"] == phase) & (work["target"] == target) & scope_mask
                    if mask.any():
                        fallback_metrics.append(
                            {
                                "phase": phase,
                                "target": target,
                                "scope": scope,
                                "fallback_candidate": fallback_candidate,
                            }
                            | central_metric_record(work.loc[mask], values[mask])
                        )
    fallback_selection = select_fallback(fallback_metrics)
    selected_fallback = fallback_selection["selected"]
    base = fallback_values[selected_fallback]
    blend_changed = materially_changed(fallback_values[CURRENT_FALLBACK], base, config)
    base_source = work["prediction_source"].astype(str).to_numpy(copy=True)
    base_source[blend_changed] = BLENDED_FALLBACK
    work["base_forecast_source"] = base_source

    hierarchy_metrics = []
    hierarchy_coherence = []
    material_changes = []
    alternative_failures = {}
    for alternative in config.alternatives:
        try:
            values, _, _ = reconcile_central(work, base, alternative)
        except ValueError as exc:
            alternative_failures[alternative] = str(exc)
            for phase in ("validation", "final_test"):
                for boundary in ("hospital_to_region", "region_to_national"):
                    hierarchy_coherence.append(
                        {
                            "phase": phase,
                            "hierarchy_alternative": alternative,
                            "boundary": boundary,
                            "cells": 0,
                            "exact_cells": 0,
                            "mean_absolute_error": None,
                            "max_absolute_error": None,
                            "absolute_error_ratio": None,
                            "exact_within_tolerance": False,
                            "ineligible_reason": str(exc),
                        }
                    )
            continue
        for phase in ("validation", "final_test"):
            phase_mask = work["phase"] == phase
            for target in config.targets:
                for level in ("hospital", "region", "national"):
                    mask = phase_mask & (work["target"] == target) & (work["level"] == level)
                    if not mask.any():
                        continue
                    hierarchy_metrics.append(
                        {"phase": phase, "target": target, "level": level, "hierarchy_alternative": alternative}
                        | central_metric_record(work.loc[mask], values[mask])
                    )
            for record in coherence_metrics(work.loc[phase_mask], values[phase_mask], config.coherence_tolerance):
                hierarchy_coherence.append({"phase": phase, "hierarchy_alternative": alternative} | record)
            child_mask = phase_mask & (work["level"] == "hospital")
            changed = materially_changed(base[child_mask], values[child_mask], config)
            material_changes.append(
                {
                    "phase": phase,
                    "hierarchy_alternative": alternative,
                    "child_rows": int(child_mask.sum()),
                    "materially_changed_child_rows": int(changed.sum()),
                    "materially_changed_child_share": float(changed.mean()) if len(changed) else 0.0,
                }
            )
    hierarchy_selection = select_hierarchy(hierarchy_metrics, hierarchy_coherence, config.coherence_tolerance)
    selected_hierarchy = hierarchy_selection["selected"]
    selected, forecast_source, hierarchy_status = reconcile_central(work, base, selected_hierarchy)
    adjusted = np.abs(selected - work["source_central_value"].to_numpy(float)) > EPSILON

    fallback_status = (
        work["fallback_level"]
        .astype(str)
        .replace(
            {
                "none": "not_applicable",
                "region_profile_share": "regional_fallback",
                "own_history_zero": "no_history_deterministic_zero",
                "own_history_seasonal": "own_history_seasonal",
                NATIONAL_PROXY: "national_historical_quantile_proxy",
            }
        )
    )
    fallback_status.loc[blend_changed] = BLENDED_FALLBACK
    support_status = np.where(
        work["supported"],
        "supported",
        np.where(work["history_total"].fillna(0) > 0, "limited_history", "no_history"),
    )
    calibration_status = work["calibration_status"].astype(str)
    uncertainty_status = np.where(
        work["level"] == "national",
        "national_proxy_not_predictive_distribution",
        np.where(
            calibration_status == "calibrated",
            np.where(adjusted, "level_local_calibrated_not_reconciled", "level_local_calibrated"),
            np.where(
                work["uncertainty_support"].astype(str).str.contains("no_estimated_uncertainty"),
                "uncertainty_unavailable",
                "calibration_support_insufficient",
            ),
        ),
    )
    output = work.copy()
    output["forecast_value"] = selected
    output["forecast_source"] = forecast_source
    output["hierarchy_status"] = hierarchy_status
    output["support_status"] = support_status
    output["fallback_status"] = fallback_status
    output["uncertainty_status"] = uncertainty_status
    output["hierarchy_alternative"] = selected_hierarchy
    output["fallback_candidate"] = selected_fallback
    output["hierarchy_adjusted"] = adjusted
    output["probabilistic_reconciliation_applied"] = False
    output["raw_quantile_semantics"] = np.where(
        output["level"] == "national",
        "historical_region_quantile_sum_proxy_not_national_distribution",
        "unchanged_model_evidence",
    )
    if not np.array_equal(raw_before, output[["raw_p10", "raw_p50", "raw_p90"]].to_numpy(), equal_nan=True):
        raise ValueError("hierarchy evaluation modified raw quantile evidence")
    return output, {
        "fallback_metrics": fallback_metrics,
        "fallback_selection": fallback_selection,
        "hierarchy_metrics": hierarchy_metrics,
        "coherence": hierarchy_coherence,
        "material_changes": material_changes,
        "alternative_failures": alternative_failures,
        "hierarchy_selection": hierarchy_selection,
        "probabilistic_reconciliation_applied": False,
        "final_test_used_for_selection": False,
    }
