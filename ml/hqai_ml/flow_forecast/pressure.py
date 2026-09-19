"""Origin-legal historical flow-pressure thresholds, warnings, and observed anomalies."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from hqai_ml.features.load import Panel
from hqai_ml.flow_forecast.calibration import date_class
from hqai_ml.flow_forecast.config import FlowPressureConfig
from hqai_ml.flow_forecast.quantile import INTERNAL_TARGETS
from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun

SEVERITY_RANK = {"UNSUPPORTED": -1, "NORMAL": 0, "WATCH": 1, "ELEVATED": 2, "HIGH": 3}
ALERT_SEVERITIES = {"WATCH", "ELEVATED", "HIGH"}
PRESSURE_SIGNAL = "preventive_flow_pressure"
ANOMALY_SIGNAL = "observed_unusual_flow"
DAILY_ALERT_UNIT = "hospital_profile_target_origin_target_day"
ENTITY_ORIGIN_ALERT_UNIT = "hospital_profile_target_origin"


def _stable_id(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def hierarchy_evaluation_key(version: str) -> CheckpointKey:
    return CheckpointKey(
        "load_forecast",
        candidate_id="flow-hierarchy-central",
        trial_id=version,
        fold_id="all-origins",
    )


def load_verified_hierarchy_forecasts(
    artifacts_dir: Path,
    source_run_id: str,
) -> tuple[pd.DataFrame, dict, dict]:
    """Read the selected hierarchy artifact through its immutable checkpoint and summary."""
    run = ExperimentRun.read_only(artifacts_dir, source_run_id)
    if run.manifest["status"] != "completed":
        raise ValueError(f"hierarchy source run {source_run_id!r} is not completed")
    hierarchy = run.manifest["hyperparameters"]["flow_hierarchy"]
    key = hierarchy_evaluation_key(hierarchy["version"])
    recorded_checkpoint = json.loads(run.checkpoint_path(key).read_text(encoding="utf-8"))
    expected_parameters = {
        "source_artifact_identity": run.manifest["hyperparameters"]["source_quantile"]["artifact_identity"],
        "calibration_scientific_identity": run.manifest["hyperparameters"]["source_calibration"]["scientific_identity"],
        "configuration_identity": recorded_checkpoint["parameters"].get("configuration_identity"),
        "alternatives": hierarchy["alternatives"],
        "fallback_candidates": hierarchy["fallback"]["candidates"],
    }
    if recorded_checkpoint["parameters"] != expected_parameters:
        raise ValueError("hierarchy evaluation checkpoint parameters are incompatible with its run manifest")
    checkpoint = run.reusable_checkpoint(key, parameters=expected_parameters)
    if checkpoint is None or checkpoint["evaluation"]["status"] != "completed":
        raise ValueError("hierarchy evaluation checkpoint is incomplete")

    summary_key = CheckpointKey.model("load_forecast")
    recorded_summary = json.loads(run.checkpoint_path(summary_key).read_text(encoding="utf-8"))
    summary_checkpoint = run.reusable_checkpoint(summary_key, parameters=recorded_summary["parameters"])
    if summary_checkpoint is None or summary_checkpoint["evaluation"]["status"] != "completed":
        raise ValueError("hierarchy summary checkpoint is incomplete")
    if recorded_summary["parameters"].get("evaluation_checkpoint") != key.identifier:
        raise ValueError("hierarchy summary does not reference the verified evaluation checkpoint")

    evaluation_artifact = artifacts_dir / checkpoint["artifact"]["path"]
    columns = [
        "phase",
        "origin",
        "target",
        "level",
        "series_id",
        "horizon",
        "target_date",
        "org_code",
        "region_code",
        "profile_code",
        "y",
        "forecast_value",
        "forecast_source",
        "hierarchy_status",
        "support_status",
        "fallback_status",
        "uncertainty_status",
        "calibration_version",
        "calibration_status",
        "level_local_interval_80_lower",
        "level_local_interval_80_upper",
        "hierarchy_alternative",
        "fallback_candidate",
    ]
    frame = pd.read_parquet(
        evaluation_artifact / "selected-central-forecast.parquet",
        columns=columns,
        filters=[("level", "==", "hospital")],
    )
    summary_artifact = artifacts_dir / summary_checkpoint["artifact"]["path"]
    summary = json.loads((summary_artifact / "summary.json").read_text(encoding="utf-8"))
    if (
        summary["run_id"] != source_run_id
        or summary["scientific_identity_sha256"] != run.manifest["scientific_identity_sha256"]
    ):
        raise ValueError("hierarchy summary identity is incompatible with the source run")
    if summary["protocol"]["final_test_used_for_selection"] or summary["automatic_promotion"]:
        raise ValueError("hierarchy source violates validation-only/non-promotion governance")
    selected_hierarchy = summary["analysis"]["hierarchy_selection"]["selected"]
    selected_fallback = summary["analysis"]["fallback_selection"]["selected"]
    if set(frame["hierarchy_alternative"]) != {selected_hierarchy} or set(frame["fallback_candidate"]) != {
        selected_fallback
    }:
        raise ValueError("hierarchy forecast rows do not match the saved validation selections")
    lineage = {
        "source_run_id": source_run_id,
        "source_scientific_identity": run.manifest["scientific_identity_sha256"],
        "source_code_identity": run.manifest["code"]["source"]["sha256"],
        "source_dataset_identity": run.manifest["dataset"]["identity_sha256"],
        "source_configuration_identity": run.manifest["configuration"]["sha256"],
        "evaluation_checkpoint_identity": checkpoint["scientific_identity_sha256"],
        "evaluation_artifact_sha256": checkpoint["artifact"]["sha256"],
        "summary_checkpoint_identity": summary_checkpoint["scientific_identity_sha256"],
        "summary_artifact_sha256": summary_checkpoint["artifact"]["sha256"],
        "selected_hierarchy": selected_hierarchy,
        "selected_fallback": selected_fallback,
    }
    return frame, lineage, summary


def _eligible_sample(
    values: np.ndarray,
    minimum_observations: int,
    minimum_positive_days: int,
) -> bool:
    return len(values) >= minimum_observations and int((values > 0).sum()) >= minimum_positive_days


def historical_flow_thresholds(
    hospital: Panel,
    region: Panel,
    origins: list[dt.date],
    targets: list[str],
    config: FlowPressureConfig,
    holidays: set[dt.date],
) -> pd.DataFrame:
    """Compute fixed origin-legal thresholds for hospital/profile forecast cells."""
    region_position = {(row.region_code, row.profile_code): index for index, row in enumerate(region.meta.itertuples())}
    records = []
    threshold = config.threshold
    for origin in origins:
        origin_index = hospital.index_of(origin)
        history_start = max(0, origin_index - threshold.history_window_days + 1)
        history_indices = np.arange(history_start, origin_index + 1)
        history_dates = [hospital.dates[index] for index in history_indices]
        date_masks = {
            kind: np.asarray([date_class(day, holidays) == kind for day in history_dates])
            for kind in ("weekday", "weekend", "holiday")
        }
        target_dates = [origin + dt.timedelta(days=horizon) for horizon in range(1, config.horizon + 1)]
        needed_classes = {date_class(day, holidays) for day in target_dates}
        for public_target in targets:
            internal_target = INTERNAL_TARGETS[public_target]
            hospital_values = hospital.target(internal_target)[:, history_indices]
            region_values = region.target(internal_target)[:, history_indices]
            for hospital_index, row in enumerate(hospital.meta.itertuples()):
                parent_index = region_position[(row.region_code, row.profile_code)]
                resolved = {}
                for kind in needed_classes:
                    own_class = hospital_values[hospital_index, date_masks[kind]]
                    own_pooled = hospital_values[hospital_index]
                    parent_class = region_values[parent_index, date_masks[kind]]
                    parent_pooled = region_values[parent_index]
                    candidates = (
                        (
                            "hospital_date_class",
                            own_class,
                            threshold.minimum_date_class_observations,
                            threshold.minimum_date_class_positive_days,
                            row.series_id,
                        ),
                        (
                            "hospital_pooled",
                            own_pooled,
                            threshold.minimum_pooled_observations,
                            threshold.minimum_pooled_positive_days,
                            row.series_id,
                        ),
                        (
                            "region_date_class",
                            parent_class,
                            threshold.minimum_date_class_observations,
                            threshold.minimum_date_class_positive_days,
                            region.meta.iloc[parent_index]["series_id"],
                        ),
                        (
                            "region_pooled",
                            parent_pooled,
                            threshold.minimum_pooled_observations,
                            threshold.minimum_pooled_positive_days,
                            region.meta.iloc[parent_index]["series_id"],
                        ),
                    )
                    selected = None
                    for level, sample, minimum_count, minimum_positive, source_series in candidates:
                        if _eligible_sample(sample, minimum_count, minimum_positive):
                            selected = {
                                "threshold_status": "supported",
                                "threshold_value": float(np.quantile(sample, threshold.quantile, method="higher")),
                                "threshold_fallback_level": level,
                                "threshold_source_series_id": str(source_series),
                                "threshold_sample_count": int(len(sample)),
                                "threshold_positive_days": int((sample > 0).sum()),
                            }
                            break
                    resolved[kind] = selected or {
                        "threshold_status": "unsupported",
                        "threshold_value": np.nan,
                        "threshold_fallback_level": "unsupported_insufficient_history",
                        "threshold_source_series_id": None,
                        "threshold_sample_count": 0,
                        "threshold_positive_days": 0,
                    }
                for horizon, target_date in enumerate(target_dates, start=1):
                    kind = date_class(target_date, holidays)
                    records.append(
                        {
                            "origin": pd.Timestamp(origin),
                            "target": public_target,
                            "series_id": str(row.series_id),
                            "horizon": horizon,
                            "target_date": pd.Timestamp(target_date),
                            "threshold_date_class": kind,
                            "threshold_history_start": pd.Timestamp(hospital.dates[history_start]),
                            "threshold_history_end": pd.Timestamp(origin),
                            "threshold_quantile": threshold.quantile,
                            "threshold_semantics": config.threshold_semantics,
                        }
                        | resolved[kind]
                    )
    return pd.DataFrame(records)


def severity_for_row(
    forecast: float,
    threshold: float | None,
    lower: float | None,
    upper: float | None,
    threshold_supported: bool,
) -> tuple[str, str]:
    if not threshold_supported or threshold is None or not np.isfinite(threshold):
        return "UNSUPPORTED", "THRESHOLD_UNSUPPORTED"
    if lower is not None and np.isfinite(lower) and lower > threshold:
        return "HIGH", "CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD"
    if forecast > threshold:
        return "ELEVATED", "CENTRAL_FORECAST_EXCEEDS_HISTORICAL_FLOW_THRESHOLD"
    if upper is not None and np.isfinite(upper) and upper > threshold:
        return "WATCH", "CALIBRATED_UPPER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD"
    return "NORMAL", "FORECAST_BELOW_HISTORICAL_FLOW_THRESHOLD"


def derive_daily_pressure_signals(
    forecasts: pd.DataFrame,
    thresholds: pd.DataFrame,
    config: FlowPressureConfig,
) -> pd.DataFrame:
    keys = ["origin", "target", "series_id", "horizon", "target_date"]
    frame = forecasts.merge(thresholds, on=keys, how="left", validate="one_to_one")
    if frame["threshold_status"].isna().any():
        raise ValueError("threshold rows do not cover every hierarchy forecast cell")
    interval_available = (
        (frame["uncertainty_status"] == "level_local_calibrated")
        & frame["level_local_interval_80_lower"].notna()
        & frame["level_local_interval_80_upper"].notna()
    )
    frame["uncertainty_lower"] = frame["level_local_interval_80_lower"].where(interval_available)
    frame["uncertainty_upper"] = frame["level_local_interval_80_upper"].where(interval_available)
    severity = [
        severity_for_row(forecast, threshold, lower, upper, status == "supported")
        for forecast, threshold, lower, upper, status in zip(
            frame["forecast_value"],
            frame["threshold_value"],
            frame["uncertainty_lower"],
            frame["uncertainty_upper"],
            frame["threshold_status"],
            strict=True,
        )
    ]
    frame["severity"] = [item[0] for item in severity]
    base_reasons = [item[1] for item in severity]
    frame["reason_codes"] = [
        [reason]
        + ([] if uncertainty else ["UNCERTAINTY_UNAVAILABLE"])
        + (["REGION_THRESHOLD_FALLBACK"] if str(fallback).startswith("region_") else [])
        + (["FORECAST_FALLBACK"] if forecast_fallback != "not_applicable" else [])
        for reason, uncertainty, fallback, forecast_fallback in zip(
            base_reasons,
            interval_available,
            frame["threshold_fallback_level"],
            frame["fallback_status"],
            strict=True,
        )
    ]
    frame["signal_id"] = [
        _stable_id(config.version, PRESSURE_SIGNAL, origin, series_id, target, horizon)
        for origin, series_id, target, horizon in zip(
            frame["origin"], frame["series_id"], frame["target"], frame["horizon"], strict=True
        )
    ]
    frame["signal_type"] = PRESSURE_SIGNAL
    frame["alert_unit"] = DAILY_ALERT_UNIT
    frame["entity_level"] = "hospital_profile"
    frame["hospital_id"] = frame["org_code"]
    frame["region_id"] = frame["region_code"]
    frame["profile_id"] = frame["profile_code"]
    frame["forecast_origin"] = frame["origin"]
    frame["data_freshness"] = frame["origin"]
    frame["actual_exceeds_threshold"] = (frame["threshold_status"] == "supported") & (
        frame["y"] > frame["threshold_value"]
    )
    frame["is_alert"] = frame["severity"].isin(ALERT_SEVERITIES)
    return frame


def aggregate_pressure_signals(daily: pd.DataFrame, config: FlowPressureConfig) -> pd.DataFrame:
    group_columns = [
        "phase",
        "origin",
        "target",
        "series_id",
        "org_code",
        "region_code",
        "profile_code",
    ]
    records = []
    for keys, part in daily.groupby(group_columns, sort=True, observed=True):
        part = part.sort_values("horizon")
        alerts = part[part["severity"].isin(ALERT_SEVERITIES)]
        first_crossing = alerts.iloc[0] if not alerts.empty else None

        def maximum(window: int, group: pd.DataFrame = part) -> str:
            values = group.loc[group["horizon"] <= window, "severity"]
            return max(values, key=lambda value: SEVERITY_RANK[value])

        def window_evidence(window: int, group: pd.DataFrame = part) -> dict:
            values = group.loc[group["horizon"] <= window]
            complete = set(values["horizon"].astype(int)) == set(range(1, window + 1))
            supported = complete and bool((values["threshold_status"] == "supported").all())
            return {
                f"any_alert_{window}d": bool(values["is_alert"].any()),
                f"max_severity_{window}d": maximum(window),
                f"actual_event_within_{window}d": (
                    bool(values["actual_exceeds_threshold"].any()) if supported else None
                ),
                f"evaluation_supported_{window}d": supported,
            }

        displayed_severity = maximum(14)
        severity_evidence = part[(part["horizon"] <= 14) & (part["severity"] == displayed_severity)].iloc[0]
        first_date = first_crossing["target_date"] if first_crossing is not None else pd.NaT
        lead_time = int(first_crossing["horizon"]) if first_crossing is not None else None
        records.append(
            dict(zip(group_columns, keys, strict=True))
            | {
                "signal_id": _stable_id(config.version, PRESSURE_SIGNAL, *keys),
                "signal_type": PRESSURE_SIGNAL,
                "alert_unit": ENTITY_ORIGIN_ALERT_UNIT,
                "severity": displayed_severity,
                "displayed_severity_basis": "max_severity_14d",
                "severity_evidence_horizon": int(severity_evidence["horizon"]),
                "severity_evidence_date": severity_evidence["target_date"],
                "entity_level": "hospital_profile",
                "hospital_id": severity_evidence["org_code"],
                "region_id": severity_evidence["region_code"],
                "profile_id": severity_evidence["profile_code"],
                "forecast_origin": severity_evidence["origin"],
                "first_crossing_date": first_date,
                "lead_time_days": lead_time,
                "first_crossing_severity": (first_crossing["severity"] if first_crossing is not None else None),
                **window_evidence(7),
                **window_evidence(14),
                "forecast_value": float(severity_evidence["forecast_value"]),
                "threshold_value": (
                    float(severity_evidence["threshold_value"])
                    if pd.notna(severity_evidence["threshold_value"])
                    else None
                ),
                "uncertainty_lower": (
                    float(severity_evidence["uncertainty_lower"])
                    if pd.notna(severity_evidence["uncertainty_lower"])
                    else None
                ),
                "uncertainty_upper": (
                    float(severity_evidence["uncertainty_upper"])
                    if pd.notna(severity_evidence["uncertainty_upper"])
                    else None
                ),
                "threshold_semantics": severity_evidence["threshold_semantics"],
                "forecast_source": severity_evidence["forecast_source"],
                "support_status": severity_evidence["support_status"],
                "fallback_status": severity_evidence["fallback_status"],
                "uncertainty_status": severity_evidence["uncertainty_status"],
                "threshold_status": severity_evidence["threshold_status"],
                "threshold_fallback_level": severity_evidence["threshold_fallback_level"],
                "reason_codes": severity_evidence["reason_codes"],
                "data_freshness": severity_evidence["data_freshness"],
                "calibration_version": severity_evidence["calibration_version"],
            }
        )
    return pd.DataFrame(records)


def retrospective_warning_metrics(daily: pd.DataFrame) -> list[dict]:
    records = []
    for (phase, target), part in daily.groupby(["phase", "target"], sort=True, observed=True):
        supported = part[part["threshold_status"] == "supported"]
        alerts = supported["is_alert"].to_numpy(bool)
        events = supported["actual_exceeds_threshold"].to_numpy(bool)
        true_positive = alerts & events
        false_positive = alerts & ~events
        non_events = ~events
        records.append(
            {
                "metric_family": "daily_cell",
                "alert_unit": DAILY_ALERT_UNIT,
                "phase": phase,
                "target": target,
                "rows": int(len(part)),
                "supported_rows": int(len(supported)),
                "unsupported_rows": int(len(part) - len(supported)),
                "supported_share": float(len(supported) / len(part)) if len(part) else None,
                "unsupported_share": float(1.0 - len(supported) / len(part)) if len(part) else None,
                "alert_count": int(alerts.sum()),
                "alert_rate": float(alerts.mean()) if len(alerts) else None,
                "event_count": int(events.sum()),
                "event_rate": float(events.mean()) if len(events) else None,
                "precision": float(true_positive.sum() / alerts.sum()) if alerts.sum() else None,
                "recall": float(true_positive.sum() / events.sum()) if events.sum() else None,
                "false_alert_rate": (float(false_positive.sum() / non_events.sum()) if non_events.sum() else None),
                "median_lead_time_days": (
                    float(supported.loc[true_positive, "horizon"].median()) if true_positive.any() else None
                ),
                "median_lead_time_definition": "median_horizon_over_true_positive_daily_alert_cells",
                "alerts_by_severity": {
                    severity: int((supported["severity"] == severity).sum())
                    for severity in ("WATCH", "ELEVATED", "HIGH")
                },
                "event_definition": "actual_observed_count_strictly_exceeds_origin_legal_historical_flow_threshold",
                "incident_semantics": "retrospective_high_flow_proxy_event_not_physical_capacity_incident",
                "incident_or_episode_level": False,
            }
        )
    return records


def entity_origin_warning_metrics(entity: pd.DataFrame) -> list[dict]:
    """Score each hospital/profile/target/origin once within 7- and 14-day windows."""
    records = []
    for (phase, target), part in entity.groupby(["phase", "target"], sort=True, observed=True):
        for window in (7, 14):
            supported_column = f"evaluation_supported_{window}d"
            alert_column = f"any_alert_{window}d"
            event_column = f"actual_event_within_{window}d"
            supported = part[part[supported_column]].copy()
            alerts = supported[alert_column].to_numpy(bool)
            events = supported[event_column].to_numpy(bool)
            true_positive = alerts & events
            false_positive = alerts & ~events
            non_events = ~events
            records.append(
                {
                    "metric_family": "entity_origin",
                    "alert_unit": ENTITY_ORIGIN_ALERT_UNIT,
                    "window_days": window,
                    "phase": phase,
                    "target": target,
                    "entity_origins": int(len(part)),
                    "supported_entity_origins": int(len(supported)),
                    "unsupported_entity_origins": int(len(part) - len(supported)),
                    "supported_share": float(len(supported) / len(part)) if len(part) else None,
                    "alert_count": int(alerts.sum()),
                    "alert_rate": float(alerts.mean()) if len(alerts) else None,
                    "event_count": int(events.sum()),
                    "event_rate": float(events.mean()) if len(events) else None,
                    "precision": float(true_positive.sum() / alerts.sum()) if alerts.sum() else None,
                    "recall": float(true_positive.sum() / events.sum()) if events.sum() else None,
                    "false_alert_rate": (float(false_positive.sum() / non_events.sum()) if non_events.sum() else None),
                    "event_definition": (
                        "any_actual_observed_count_strictly_exceeds_origin_legal_historical_flow_threshold"
                        f"_within_{window}d"
                    ),
                    "incident_or_episode_level": False,
                }
            )
    return records


def observed_flow_anomalies(
    hospital: Panel,
    origins: list[dt.date],
    config: FlowPressureConfig,
) -> pd.DataFrame:
    anomaly = config.anomaly
    values = hospital.registrations
    records = []
    for origin in origins:
        origin_index = hospital.index_of(origin)
        reference_start = max(7, origin_index - anomaly.lookback_days)
        reference_indices = np.arange(reference_start, origin_index)
        residuals = values[:, reference_indices] - values[:, reference_indices - 7]
        current_residual = values[:, origin_index] - values[:, origin_index - 7]
        median = np.median(residuals, axis=1) if residuals.shape[1] else np.zeros(len(hospital.meta))
        mad = np.median(np.abs(residuals - median[:, None]), axis=1) if residuals.shape[1] else np.zeros(len(median))
        scale = 1.4826 * mad
        supported = (residuals.shape[1] >= anomaly.minimum_residuals) & (scale > 0)
        robust_z = np.full(len(hospital.meta), np.nan)
        robust_z[supported] = (current_residual[supported] - median[supported]) / scale[supported]
        flagged = supported & (np.abs(robust_z) >= anomaly.robust_z_threshold)
        for index, row in enumerate(hospital.meta.itertuples()):
            status = "UNSUPPORTED"
            reason = "ANOMALY_REFERENCE_UNSUPPORTED"
            if supported[index]:
                status = (
                    "UNUSUAL_HIGH"
                    if flagged[index] and robust_z[index] > 0
                    else ("UNUSUAL_LOW" if flagged[index] else "NORMAL")
                )
                reason = (
                    "OBSERVED_WEEKLY_RESIDUAL_EXCEEDS_ROBUST_THRESHOLD"
                    if flagged[index]
                    else "OBSERVED_WEEKLY_RESIDUAL_WITHIN_ROBUST_THRESHOLD"
                )
            records.append(
                {
                    "signal_id": _stable_id(config.version, ANOMALY_SIGNAL, origin, row.series_id),
                    "signal_type": ANOMALY_SIGNAL,
                    "severity": "ELEVATED" if flagged[index] else ("NORMAL" if supported[index] else "UNSUPPORTED"),
                    "anomaly_status": status,
                    "entity_level": "hospital_profile",
                    "hospital_id": row.org_code,
                    "region_id": row.region_code,
                    "profile_id": row.profile_code,
                    "series_id": row.series_id,
                    "forecast_origin": pd.Timestamp(origin),
                    "observed_value": float(values[index, origin_index]),
                    "weekly_residual": float(current_residual[index]),
                    "reference_median_residual": float(median[index]),
                    "reference_mad": float(mad[index]),
                    "robust_z": float(robust_z[index]) if np.isfinite(robust_z[index]) else None,
                    "reference_sample_count": int(residuals.shape[1]),
                    "reference_max_date": pd.Timestamp(hospital.dates[origin_index - 1]),
                    "data_freshness": pd.Timestamp(origin),
                    "reason_codes": [reason],
                    "causal_claim": False,
                }
            )
    return pd.DataFrame(records)


def representative_examples(entity_signals: pd.DataFrame, anomalies: pd.DataFrame) -> dict:
    warning = entity_signals[
        entity_signals["severity"].isin(ALERT_SEVERITIES) & entity_signals["support_status"].eq("supported")
    ]
    fallback = entity_signals[
        entity_signals["fallback_status"].isin(["regional_fallback", "support_weighted_parent_own_blend"])
    ]
    unavailable = entity_signals[entity_signals["uncertainty_status"].ne("level_local_calibrated")]
    registration_warning = warning[warning["target"].eq("registrations")]
    if not registration_warning.empty:
        warning = registration_warning
    anomaly = anomalies[anomalies["anomaly_status"].isin(["UNUSUAL_HIGH", "UNUSUAL_LOW"])].merge(
        entity_signals[["origin", "series_id", "severity"]].rename(columns={"origin": "forecast_origin"}),
        on=["forecast_origin", "series_id"],
        how="left",
    )
    anomaly_only = anomaly[~anomaly["severity_y"].isin(ALERT_SEVERITIES)] if not anomaly.empty else anomaly

    def one(frame: pd.DataFrame, reason: str) -> dict:
        if frame.empty:
            return {"available": False, "reason": reason}
        row = json.loads(frame.iloc[[0]].to_json(orient="records", date_format="iso"))[0]
        return {"available": True, "example": row}

    return {
        "supported_future_warning": one(warning, "no supported future warning in evaluated artifacts"),
        "regional_fallback_hospital": one(fallback, "no regional fallback row in evaluated artifacts"),
        "uncertainty_unavailable": one(unavailable, "no uncertainty-unavailable row in evaluated artifacts"),
        "observed_anomaly_without_future_warning": one(
            anomaly_only,
            "no observed anomaly without a future warning in evaluated artifacts",
        ),
    }
