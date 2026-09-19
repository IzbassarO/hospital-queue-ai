"""Origin-legal temporal calibration of saved raw flow-quantile predictions."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from hqai_ml.flow_forecast.config import TemporalCalibrationConfig
from hqai_ml.flow_forecast.quantile import NATIONAL_PROXY, RAW_VARIANT
from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun

PRIMARY_METHOD = "conformal_interval_expansion"
BASELINE_METHOD = "median_absolute_residual_baseline"
CALIBRATED = "calibrated"
OWN_HISTORY_UNSUPPORTED = "unsupported_own_history_no_uncertainty"
NATIONAL_PROXY_UNSUPPORTED = "unsupported_national_region_quantile_sum_proxy"
INSUFFICIENT = "insufficient_calibration_support"
SOURCE_COMPATIBILITY_COMPONENTS = (
    "models",
    "candidates",
    "model_families",
    "prediction_targets",
    "dataset_identity",
    "config_identity",
    "implementation_versions",
    "temporal_protocols",
    "hyperparameters",
    "random_seeds",
)


def calibration_version(config: TemporalCalibrationConfig) -> str:
    return f"{config.version}-{config.identity_sha256[:12]}"


def date_class(target_date: pd.Timestamp | dt.date, holidays: set[dt.date]) -> str:
    day = target_date.date() if isinstance(target_date, pd.Timestamp) else target_date
    if day in holidays:
        return "holiday"
    return "weekend" if day.isoweekday() >= 6 else "weekday"


def calibration_support_class(frame: pd.DataFrame) -> pd.Series:
    result = pd.Series("unsupported_unknown", index=frame.index, dtype="object")
    national = (frame["level"] == "national") | (frame["aggregation_method"] == NATIONAL_PROXY)
    result.loc[national] = "national_proxy"
    own_history = frame["fallback_level"].isin(["own_history_zero", "own_history_seasonal"])
    result.loc[own_history & ~national] = "own_history_no_uncertainty"
    parent = frame["fallback_level"] == "region_profile_share"
    result.loc[parent & ~national] = "region_profile_share_fallback"
    direct = (frame["prediction_source"] == "direct_quantile_ml") & ~national
    result.loc[direct] = "direct_quantile_ml"
    return result


def interval_conformity_score(
    y: np.ndarray,
    raw_lower: np.ndarray,
    raw_upper: np.ndarray,
) -> np.ndarray:
    """Non-negative amount required to symmetrically expand the raw interval to contain y."""
    y, raw_lower, raw_upper = (np.asarray(values, dtype=float) for values in (y, raw_lower, raw_upper))
    return np.maximum.reduce([raw_lower - y, y - raw_upper, np.zeros_like(y)])


def median_absolute_residual_score(y: np.ndarray, raw_median: np.ndarray) -> np.ndarray:
    return np.abs(np.asarray(y, dtype=float) - np.asarray(raw_median, dtype=float))


def finite_sample_quantile(scores: np.ndarray, coverage: float) -> float:
    values = np.sort(np.asarray(scores, dtype=float))
    values = values[np.isfinite(values)]
    if len(values) == 0:
        raise ValueError("cannot calibrate without finite conformity scores")
    rank = min(len(values), int(np.ceil((len(values) + 1) * coverage)))
    return float(values[rank - 1])


def eligible_temporal_pool(frame: pd.DataFrame, origin: dt.date) -> pd.DataFrame:
    origin_timestamp = pd.Timestamp(origin)
    pool = frame[
        (frame["phase"] == "validation")
        & (frame["origin"] < origin_timestamp)
        & (frame["target_date"] <= origin_timestamp)
    ].copy()
    assert_temporal_pool_legal(pool, origin)
    return pool


def assert_temporal_pool_legal(pool: pd.DataFrame, origin: dt.date) -> None:
    if pool.empty:
        return
    cutoff = pd.Timestamp(origin)
    if (pool["phase"] != "validation").any():
        raise ValueError("final-test forecasts cannot supply calibration outcomes")
    if (pool["origin"] >= cutoff).any():
        raise ValueError("calibration forecasts must originate strictly before the calibrated origin")
    if (pool["target_date"] > cutoff).any():
        raise ValueError("calibration uses outcomes not observable at the calibrated origin")


def _ladder_mask(pool: pd.DataFrame, key: dict, ladder_level: str) -> pd.Series:
    mask = (
        (pool["target"] == key["target"])
        & (pool["level"] == key["level"])
        & (pool["calibration_support_class"] == key["calibration_support_class"])
    )
    if ladder_level in {"support_horizon_date_class", "support_horizon"}:
        mask &= pool["horizon"] == key["horizon"]
    if ladder_level in {"support_horizon_date_class", "support_date_class"}:
        mask &= pool["date_class"] == key["date_class"]
    return mask


def select_calibration_group(
    pool: pd.DataFrame,
    key: dict,
    score_column: str,
    config: TemporalCalibrationConfig,
) -> dict:
    for ladder_level in config.fallback_ladder:
        selected = pool.loc[_ladder_mask(pool, key, ladder_level)]
        score_count = int(selected[score_column].notna().sum())
        unique_dates = int(selected.loc[selected[score_column].notna(), "target_date"].nunique())
        if score_count >= config.minimum_scores and unique_dates >= config.minimum_unique_target_dates:
            return {
                "calibration_status": CALIBRATED,
                "calibration_group_level": ladder_level,
                "calibration_score": finite_sample_quantile(
                    selected[score_column].to_numpy(float), config.nominal_coverage
                ),
                "calibration_sample_count": score_count,
                "calibration_unique_target_dates": unique_dates,
                "calibration_source_max_target_date": selected["target_date"].max(),
                "calibration_source_max_origin": selected["origin"].max(),
            }
    return {
        "calibration_status": INSUFFICIENT,
        "calibration_group_level": None,
        "calibration_score": np.nan,
        "calibration_sample_count": 0,
        "calibration_unique_target_dates": 0,
        "calibration_source_max_target_date": pd.NaT,
        "calibration_source_max_origin": pd.NaT,
    }


def _parameter_table(
    current: pd.DataFrame,
    pool: pd.DataFrame,
    method: str,
    config: TemporalCalibrationConfig,
) -> pd.DataFrame:
    group_columns = ["target", "level", "calibration_support_class", "horizon", "date_class"]
    keys = current[group_columns].drop_duplicates().to_dict("records")
    score_column = "interval_conformity_score" if method == PRIMARY_METHOD else "median_absolute_residual_score"
    records = []
    for key in keys:
        support_class = key["calibration_support_class"]
        if support_class == "national_proxy":
            result = {
                "calibration_status": NATIONAL_PROXY_UNSUPPORTED,
                "calibration_group_level": None,
                "calibration_score": np.nan,
                "calibration_sample_count": 0,
                "calibration_unique_target_dates": 0,
                "calibration_source_max_target_date": pd.NaT,
                "calibration_source_max_origin": pd.NaT,
            }
        elif support_class == "own_history_no_uncertainty":
            result = {
                "calibration_status": OWN_HISTORY_UNSUPPORTED,
                "calibration_group_level": None,
                "calibration_score": np.nan,
                "calibration_sample_count": 0,
                "calibration_unique_target_dates": 0,
                "calibration_source_max_target_date": pd.NaT,
                "calibration_source_max_origin": pd.NaT,
            }
        else:
            result = select_calibration_group(pool, key, score_column, config)
        records.append(key | {"calibration_method": method} | result)
    return pd.DataFrame(records)


def calibrate_origin(
    source: pd.DataFrame,
    origin: dt.date,
    config: TemporalCalibrationConfig,
    holidays: set[dt.date],
) -> tuple[pd.DataFrame, dict]:
    required = {
        "phase",
        "origin",
        "target_date",
        "candidate",
        "variant",
        "target",
        "level",
        "series_id",
        "horizon",
        "y",
        "p10",
        "p50",
        "p90",
        "fallback_level",
        "prediction_source",
        "aggregation_method",
    }
    missing = required - set(source.columns)
    if missing:
        raise ValueError(f"source raw prediction artifacts are missing columns: {sorted(missing)}")
    eligible = source[(source["candidate"] == config.candidate) & (source["variant"] == RAW_VARIANT)].copy()
    eligible["calibration_support_class"] = calibration_support_class(eligible)
    eligible["date_class"] = [date_class(day, holidays) for day in eligible["target_date"]]
    eligible["interval_conformity_score"] = interval_conformity_score(eligible["y"], eligible["p10"], eligible["p90"])
    eligible["median_absolute_residual_score"] = median_absolute_residual_score(eligible["y"], eligible["p50"])
    current = eligible[eligible["origin"] == pd.Timestamp(origin)].copy()
    if current.empty:
        raise ValueError(f"source run has no raw predictions for origin {origin}")
    current[["raw_p10", "raw_p50", "raw_p90"]] = current[["p10", "p50", "p90"]].to_numpy()
    pool = eligible_temporal_pool(eligible, origin)
    raw_before = current[["raw_p10", "raw_p50", "raw_p90"]].to_numpy(copy=True)
    outputs = []
    for method in config.methods:
        parameters = _parameter_table(current, pool, method, config)
        group_columns = ["target", "level", "calibration_support_class", "horizon", "date_class"]
        calibrated = current.merge(parameters, on=group_columns, how="left", validate="many_to_one")
        calibrated["calibration_version"] = calibration_version(config)
        calibrated["calibration_nominal_coverage"] = config.nominal_coverage
        calibrated["calibration_origin_cutoff"] = pd.Timestamp(origin)
        score = calibrated["calibration_score"].to_numpy(float)
        if method == PRIMARY_METHOD:
            lower = calibrated["raw_p10"].to_numpy(float) - score
            upper = calibrated["raw_p90"].to_numpy(float) + score
        else:
            lower = calibrated["raw_p50"].to_numpy(float) - score
            upper = calibrated["raw_p50"].to_numpy(float) + score
        supported = calibrated["calibration_status"] == CALIBRATED
        nonnegative_lower = np.maximum(0.0, lower)
        ordered_upper = np.maximum(nonnegative_lower, upper)
        calibrated["calibrated_interval_80_lower"] = np.where(supported, nonnegative_lower, np.nan)
        calibrated["calibrated_interval_80_upper"] = np.where(supported, ordered_upper, np.nan)
        calibrated["calibrated_lower_nonnegative_transform"] = np.where(
            supported,
            "max_zero",
            "not_applicable",
        )
        calibrated["direct_or_fallback"] = np.where(
            calibrated["calibration_support_class"] == "direct_quantile_ml",
            "direct",
            "fallback",
        )
        outputs.append(calibrated)
    result = pd.concat(outputs, ignore_index=True)
    for method in config.methods:
        values = result.loc[
            result["calibration_method"] == method,
            ["raw_p10", "raw_p50", "raw_p90"],
        ].to_numpy()
        if not np.array_equal(raw_before, values, equal_nan=True):
            raise ValueError("calibration modified raw quantile predictions")
    audit = {
        "origin": str(origin),
        "calibration_pool_rows": int(len(pool)),
        "calibration_pool_origins": sorted(str(pd.Timestamp(day).date()) for day in pool["origin"].unique()),
        "calibration_pool_max_target_date": (str(pool["target_date"].max().date()) if not pool.empty else None),
        "all_pool_targets_observable_by_origin": bool(pool.empty or pool["target_date"].max() <= pd.Timestamp(origin)),
        "final_test_rows_in_calibration_pool": int((pool["phase"] == "final_test").sum()),
        "raw_prediction_sha256": hashlib.sha256(raw_before.tobytes()).hexdigest(),
    }
    return result, audit


def interval_score(
    y: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    nominal_coverage: float,
) -> np.ndarray:
    alpha = 1.0 - nominal_coverage
    y, lower, upper = (np.asarray(values, dtype=float) for values in (y, lower, upper))
    return upper - lower + (2.0 / alpha) * (lower - y) * (y < lower) + (2.0 / alpha) * (y - upper) * (y > upper)


def calibration_metric_record(frame: pd.DataFrame, nominal_coverage: float) -> dict:
    supported = frame[frame["calibration_status"] == CALIBRATED].copy()
    if supported.empty:
        return {
            "rows": int(len(frame)),
            "calibrated_rows": 0,
            "empirical_coverage_80": None,
            "coverage_gap_from_0_80": None,
            "interval_width_mean": None,
            "interval_score_mean": None,
            "wis_compatible_score_mean": None,
            "outcome_sample_count": 0,
            "unique_target_dates": 0,
        }
    y = supported["y"].to_numpy(float)
    lower = supported["calibrated_interval_80_lower"].to_numpy(float)
    upper = supported["calibrated_interval_80_upper"].to_numpy(float)
    median = supported["raw_p50"].to_numpy(float)
    covered = (lower <= y) & (y <= upper)
    score = interval_score(y, lower, upper, nominal_coverage)
    alpha = 1.0 - nominal_coverage
    wis_compatible = (0.5 * np.abs(y - median) + (alpha / 2.0) * score) / 1.5
    empirical = float(covered.mean())
    return {
        "rows": int(len(frame)),
        "calibrated_rows": int(len(supported)),
        "empirical_coverage_80": empirical,
        "coverage_gap_from_0_80": empirical - nominal_coverage,
        "interval_width_mean": float((upper - lower).mean()),
        "interval_score_mean": float(score.mean()),
        "wis_compatible_score_mean": float(wis_compatible.mean()),
        "outcome_sample_count": int(len(supported)),
        "unique_target_dates": int(supported["target_date"].nunique()),
        "calibration_sample_count_min": int(supported["calibration_sample_count"].min()),
        "calibration_sample_count_median": float(supported["calibration_sample_count"].median()),
    }


def _grouped_metrics(
    frame: pd.DataFrame,
    columns: list[str],
    nominal_coverage: float,
) -> list[dict]:
    records = []
    for keys, part in frame.groupby(columns, sort=True, observed=True):
        keys = keys if isinstance(keys, tuple) else (keys,)
        records.append(dict(zip(columns, keys, strict=True)) | calibration_metric_record(part, nominal_coverage))
    return records


def summarize_calibration(frame: pd.DataFrame, config: TemporalCalibrationConfig) -> dict:
    base = ["phase", "calibration_method", "target", "level"]
    non_national = frame[frame["level"] != "national"]
    return {
        "nominal_coverage": config.nominal_coverage,
        "acceptance_decision_made": False,
        "national_proxy_calibration_claimed": False,
        "canonical_hospital_region": _grouped_metrics(non_national, base, config.nominal_coverage),
        "by_horizon": _grouped_metrics(non_national, base + ["horizon"], config.nominal_coverage),
        "by_support_class": _grouped_metrics(
            non_national, base + ["calibration_support_class"], config.nominal_coverage
        ),
        "by_date_class": _grouped_metrics(non_national, base + ["date_class"], config.nominal_coverage),
        "direct_vs_fallback": _grouped_metrics(non_national, base + ["direct_or_fallback"], config.nominal_coverage),
        "support_status": [
            dict(zip([*base, "calibration_status"], keys, strict=True))
            | {"rows": int(len(part)), "series": int(part["series_id"].nunique())}
            for keys, part in frame.groupby([*base, "calibration_status"], sort=True, observed=True)
        ],
    }


def source_origin_key(origin: dt.date, phase: str) -> CheckpointKey:
    return CheckpointKey(
        "load_forecast",
        candidate_id="flow-quantile-evidence",
        trial_id="fixed",
        fold_id=phase,
        forecast_origin=origin.isoformat(),
    )


def verify_source_compatibility(source_manifest: dict, current_source_plan: dict) -> dict:
    """Require the saved quantile protocol to match, while treating code as audit lineage."""
    source = source_manifest.get("scientific_identity", {})
    current = current_source_plan.get("scientific_identity", {})
    missing = [
        f"{side}.{component}"
        for side, identity in (("source", source), ("current", current))
        for component in (*SOURCE_COMPATIBILITY_COMPONENTS, "code_identity")
        if component not in identity
    ]
    if missing:
        raise ValueError(f"source compatibility metadata is incomplete: {missing}")
    mismatches = [component for component in SOURCE_COMPATIBILITY_COMPONENTS if source[component] != current[component]]
    if mismatches:
        raise ValueError(
            "source quantile scientific protocol is incompatible with the current source plan; "
            f"mismatched components: {mismatches}"
        )
    return {
        "compatible": True,
        "equality_required_components": list(SOURCE_COMPATIBILITY_COMPONENTS),
        "code_identity_equality_required": False,
        "source_code_identity": source["code_identity"],
        "current_code_identity": current["code_identity"],
        "code_identity_equal": source["code_identity"] == current["code_identity"],
    }


def load_verified_source_predictions(
    artifacts_dir: Path,
    source_run_id: str,
    current_source_plan: dict,
    phases: list[tuple[dt.date, str]],
    checkpoint_parameters: dict,
    candidate: str,
) -> tuple[pd.DataFrame, dict]:
    source_run = ExperimentRun.read_only(artifacts_dir, source_run_id)
    if source_run.manifest["status"] != "completed":
        raise ValueError(f"source run {source_run_id!r} is not completed")
    recorded_identity = source_run.manifest["scientific_identity_sha256"]
    compatibility = verify_source_compatibility(source_run.manifest, current_source_plan)
    frames = []
    lineage = []
    for origin, phase in phases:
        key = source_origin_key(origin, phase)
        checkpoint = source_run.reusable_checkpoint(key, parameters=checkpoint_parameters)
        if checkpoint is None or checkpoint["evaluation"]["status"] != "completed":
            raise ValueError(f"source origin checkpoint is incomplete: {phase} {origin}")
        artifact = artifacts_dir / checkpoint["artifact"]["path"]
        metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
        resources = metadata["resources"]
        if resources["origin"] != str(origin) or resources["phase"] != phase:
            raise ValueError(f"source origin metadata mismatch: {phase} {origin}")
        frame = pd.read_parquet(artifact / "evaluation.parquet")
        selected = frame[(frame["candidate"] == candidate) & (frame["variant"] == RAW_VARIANT)].copy()
        if selected.empty:
            raise ValueError(f"source origin has no raw {candidate} rows: {phase} {origin}")
        if set(pd.to_datetime(selected["origin"]).dt.date) != {origin} or set(selected["phase"]) != {phase}:
            raise ValueError(f"source evaluation row identity mismatch: {phase} {origin}")
        frames.append(selected)
        lineage.append(
            {
                "origin": str(origin),
                "phase": phase,
                "checkpoint_identity": checkpoint["scientific_identity_sha256"],
                "artifact_path": checkpoint["artifact"]["path"],
                "artifact_sha256": checkpoint["artifact"]["sha256"],
            }
        )
    combined = pd.concat(frames, ignore_index=True)
    source_identity = source_run.manifest["scientific_identity"]
    return combined, {
        "source_run_id": source_run_id,
        "source_scientific_identity": recorded_identity,
        "source_code_identity": source_identity["code_identity"],
        "current_code_identity": current_source_plan["scientific_identity"]["code_identity"],
        "source_dataset_identity": source_identity["dataset_identity"],
        "source_configuration_identity": source_identity["config_identity"],
        "source_temporal_protocols": source_identity["temporal_protocols"],
        "source_artifact_checksums": {f"{item['phase']}:{item['origin']}": item["artifact_sha256"] for item in lineage},
        "compatibility": compatibility,
        "origin_artifacts": lineage,
    }
