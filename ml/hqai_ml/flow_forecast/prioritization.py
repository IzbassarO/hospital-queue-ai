"""Deterministic entity/origin Signals Inbox preparation and source verification."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from hqai_ml.flow_forecast.config import SignalPrioritizationConfig
from hqai_ml.flow_forecast.pressure import ALERT_SEVERITIES, ENTITY_ORIGIN_ALERT_UNIT, severity_for_row
from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun

PRESSURE_SIGNAL = "preventive_flow_pressure"
ANOMALY_SIGNAL = "observed_unusual_flow"
CANONICAL_KEY = ["phase", "origin", "target", "hospital_id", "profile_id"]
RANK_PARTITION = ["phase", "origin", "target"]
SEVERITY_PRIORITY = {"HIGH": 0, "ELEVATED": 1, "WATCH": 2}
FALLBACK_STATUSES = {"regional_fallback", "support_weighted_parent_own_blend", "no_history_deterministic_zero"}
NON_CAUSAL_TERMS = (" caused ", " causes ", " causal ", " driver ", " drives ", " attributable ")
LOW_VOLUME_MATERIALITY_STATUS = "zero_baseline_low_volume"


def pressure_source_key(version: str) -> CheckpointKey:
    return CheckpointKey(
        "load_forecast",
        candidate_id="preventive-flow-pressure",
        trial_id=version,
        fold_id="all-origins",
    )


def prioritization_key(version: str) -> CheckpointKey:
    return CheckpointKey(
        "load_forecast",
        candidate_id="signals-inbox",
        trial_id=version,
        fold_id="all-origins",
    )


def _require_source_contract(
    manifest: dict,
    summary: dict,
    entity: pd.DataFrame,
    config: SignalPrioritizationConfig,
) -> None:
    if summary.get("run_id") != manifest.get("run_id"):
        raise ValueError("pressure summary run identity does not match its manifest")
    if summary.get("scientific_identity_sha256") != manifest.get("scientific_identity_sha256"):
        raise ValueError("pressure summary scientific identity does not match its manifest")
    if summary.get("signal_contract", {}).get("version") != config.source_signal_contract_version:
        raise ValueError("pressure source signal contract is incompatible with Signals Inbox")
    if summary.get("alert_units", {}).get("entity_origin") != config.source_alert_unit:
        raise ValueError("pressure source does not declare the required entity/origin alert unit")
    if summary.get("protocol", {}).get("final_test_used_for_rule_selection"):
        raise ValueError("pressure source improperly used final-test evidence for rule selection")
    governance = summary.get("governance", {})
    if (
        summary.get("automatic_promotion")
        or governance.get("autonomous_action")
        or not governance.get("human_review_required")
    ):
        raise ValueError("pressure source violates non-promotion/human-review governance")

    required = {
        *CANONICAL_KEY,
        "series_id",
        "signal_type",
        "alert_unit",
        "severity",
        "max_severity_7d",
        "max_severity_14d",
        "severity_evidence_horizon",
        "severity_evidence_date",
        "displayed_severity_basis",
        "forecast_value",
        "threshold_value",
        "uncertainty_lower",
        "uncertainty_upper",
        "threshold_status",
        "reason_codes",
    }
    missing = sorted(required - set(entity.columns))
    if missing:
        raise ValueError(f"pressure source is missing corrected entity fields: {missing}")
    if set(entity["signal_type"]) != {PRESSURE_SIGNAL}:
        raise ValueError("Signals Inbox source contains a non-pressure entity signal type")
    if set(entity["alert_unit"]) != {ENTITY_ORIGIN_ALERT_UNIT}:
        raise ValueError("Signals Inbox source contains daily-cell or unknown alert units")
    if entity.duplicated(CANONICAL_KEY).any():
        raise ValueError("pressure source contains duplicate entity/origin signal rows")
    if not entity["max_severity_14d"].equals(entity["severity"]):
        raise ValueError("pressure source displayed severity differs from max_severity_14d")


def assert_displayed_evidence_consistency(entity: pd.DataFrame) -> None:
    """Require each entity's displayed numbers to reproduce its displayed severity and reason."""
    for row in entity.itertuples(index=False):
        severity, reason = severity_for_row(
            row.forecast_value,
            row.threshold_value,
            row.uncertainty_lower,
            row.uncertainty_upper,
            row.threshold_status == "supported",
        )
        if severity != row.severity or reason not in row.reason_codes:
            raise ValueError(
                f"pressure entity evidence does not reproduce displayed severity for {row.series_id!r} at {row.origin}"
            )
        expected_date = pd.Timestamp(row.origin) + pd.Timedelta(days=int(row.severity_evidence_horizon))
        if pd.Timestamp(row.severity_evidence_date) != expected_date:
            raise ValueError("pressure severity evidence date does not match its horizon")


def load_verified_pressure_signals(
    artifacts_dir: Path,
    source_run_id: str,
    config: SignalPrioritizationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict, dict]:
    """Load immutable entity/anomaly pressure artifacts; daily cells remain evidence-only and unread."""
    run = ExperimentRun.read_only(artifacts_dir, source_run_id)
    if run.manifest["status"] != "completed":
        raise ValueError(f"pressure source run {source_run_id!r} is not completed")
    pressure = run.manifest["hyperparameters"]["flow_pressure"]
    key = pressure_source_key(pressure["version"])
    recorded = json.loads(run.checkpoint_path(key).read_text(encoding="utf-8"))
    source_hierarchy = run.manifest["hyperparameters"]["source_hierarchy"]
    expected_source_parameters = {
        "source_run_id": source_hierarchy["source_run_id"],
        "source_scientific_identity": source_hierarchy["source_scientific_identity"],
        "source_evaluation_artifact_sha256": source_hierarchy["evaluation_artifact_sha256"],
        "threshold_semantics": pressure["threshold_semantics"],
        "fixed_rule_no_tuning": True,
    }
    if {key: recorded["parameters"].get(key) for key in expected_source_parameters} != expected_source_parameters:
        raise ValueError("pressure source checkpoint parameters conflict with its run manifest")
    checkpoint = run.reusable_checkpoint(key, parameters=recorded["parameters"])
    if checkpoint is None or checkpoint["evaluation"]["status"] != "completed":
        raise ValueError("pressure source evaluation checkpoint is incomplete")

    summary_key = CheckpointKey.model("load_forecast")
    recorded_summary = json.loads(run.checkpoint_path(summary_key).read_text(encoding="utf-8"))
    summary_checkpoint = run.reusable_checkpoint(summary_key, parameters=recorded_summary["parameters"])
    if summary_checkpoint is None or summary_checkpoint["evaluation"]["status"] != "completed":
        raise ValueError("pressure source summary checkpoint is incomplete")
    if recorded_summary["parameters"].get("evaluation_checkpoint") != key.identifier:
        raise ValueError("pressure source summary does not reference its verified evaluation checkpoint")

    artifact = artifacts_dir / checkpoint["artifact"]["path"]
    entity = pd.read_parquet(artifact / "entity-pressure-signals.parquet")
    anomalies = pd.read_parquet(artifact / "observed-flow-anomalies.parquet")
    summary_artifact = artifacts_dir / summary_checkpoint["artifact"]["path"]
    summary = json.loads((summary_artifact / "summary.json").read_text(encoding="utf-8"))
    _require_source_contract(run.manifest, summary, entity, config)
    assert_displayed_evidence_consistency(entity)
    if set(anomalies["signal_type"]) != {ANOMALY_SIGNAL}:
        raise ValueError("observed anomaly artifact contains an incompatible signal type")

    lineage = {
        "source_run_id": source_run_id,
        "source_scientific_identity": run.manifest["scientific_identity_sha256"],
        "source_code_identity": run.manifest["code"]["source"]["sha256"],
        "source_dataset_identity": run.manifest["dataset"]["identity_sha256"],
        "source_configuration_identity": run.manifest["configuration"]["sha256"],
        "source_signal_contract_version": pressure["version"],
        "source_alert_unit": summary["alert_units"]["entity_origin"],
        "evaluation_checkpoint_identity": checkpoint["scientific_identity_sha256"],
        "evaluation_artifact_sha256": checkpoint["artifact"]["sha256"],
        "summary_checkpoint_identity": summary_checkpoint["scientific_identity_sha256"],
        "summary_artifact_sha256": summary_checkpoint["artifact"]["sha256"],
        "daily_cells_loaded": False,
    }
    return entity, anomalies, lineage, summary


def _direct_supported(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["support_status"].eq("supported")
        & frame["fallback_status"].eq("not_applicable")
        & ~frame["forecast_source"].astype(str).str.contains("fallback", case=False)
    )


def _calibrated_uncertainty(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["uncertainty_status"].eq("level_local_calibrated")
        & frame["uncertainty_lower"].notna()
        & frame["uncertainty_upper"].notna()
    )


def _add_anomaly_context(entity: pd.DataFrame, anomalies: pd.DataFrame) -> pd.DataFrame:
    flagged = anomalies[anomalies["anomaly_status"].isin(["UNUSUAL_HIGH", "UNUSUAL_LOW"])][
        ["forecast_origin", "series_id", "anomaly_status"]
    ].drop_duplicates(["forecast_origin", "series_id"])
    flagged["target"] = "registrations"
    result = entity.merge(
        flagged.rename(columns={"forecast_origin": "origin", "anomaly_status": "observed_anomaly_status"}),
        on=["origin", "series_id", "target"],
        how="left",
        validate="many_to_one",
    )
    result["observed_anomaly_present"] = result["observed_anomaly_status"].notna()
    result["observed_anomaly_status"] = result["observed_anomaly_status"].fillna("none")
    return result


def _headline(severity: str, lead_time: int | float | None, materiality_status: str) -> str:
    if materiality_status == LOW_VOLUME_MATERIALITY_STATUS:
        return "Low-volume zero-baseline signal for review."
    if severity == "NORMAL":
        return "No future flow-pressure warning."
    label = {"HIGH": "High", "ELEVATED": "Elevated", "WATCH": "Potential"}.get(severity)
    if label is None:
        return "Pressure assessment unavailable."
    days = int(lead_time) if lead_time is not None and pd.notna(lead_time) else None
    timing = f" within {days} {'day' if days == 1 else 'days'}" if days is not None else ""
    return f"{label} flow pressure expected{timing}."


def _concise_reason(severity: str, materiality_status: str, floor: float) -> str:
    if materiality_status == LOW_VOLUME_MATERIALITY_STATUS:
        return (
            "Source threshold crossing is preserved, but the central forecast is below the fixed "
            f"{floor:.1f} expected count/day materiality floor."
        )
    return {
        "HIGH": "Calibrated lower forecast bound exceeds the hospital/profile historical high-flow threshold.",
        "ELEVATED": "Central forecast exceeds the hospital/profile historical high-flow threshold.",
        "WATCH": "Calibrated upper forecast bound exceeds the hospital/profile historical high-flow threshold.",
        "UNSUPPORTED": "Insufficient history to produce a reliable pressure assessment.",
    }.get(severity, "No future high-flow threshold crossing is present.")


def _evidence_facts(row) -> list[str]:
    fallback = row.fallback_status in FALLBACK_STATUSES or row.support_status != "supported"
    support_fact = (
        "Forecast uses regional fallback because local history is limited."
        if row.fallback_status in {"regional_fallback", "support_weighted_parent_own_blend"}
        else (
            "Local history is unavailable; deterministic zero-history fallback is shown."
            if row.fallback_status == "no_history_deterministic_zero"
            else ("Forecast support is limited." if fallback else "Forecast uses direct model support.")
        )
    )
    uncertainty_fact = (
        "Calibrated uncertainty is available." if row.uncertainty_available else "Estimated uncertainty is unavailable."
    )
    day = pd.Timestamp(row.severity_evidence_date).date().isoformat()
    evidence_fact = f"Displayed severity evidence is horizon {int(row.severity_evidence_horizon)} on {day}."
    facts = [support_fact, uncertainty_fact, evidence_fact]
    if row.materiality_status == LOW_VOLUME_MATERIALITY_STATUS:
        facts.append(
            f"Source severity {row.source_severity} is preserved; operational priority is deferred below "
            f"{row.materiality_floor_expected_count:.1f} expected count/day."
        )
    return facts


def _add_explanations(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        result["headline"] = pd.Series(index=result.index, dtype="object")
        result["concise_reason"] = pd.Series(index=result.index, dtype="object")
        result["evidence_facts"] = pd.Series(index=result.index, dtype="object")
        return result
    result["headline"] = [
        _headline(row.source_severity, row.lead_time_days, row.materiality_status) for row in result.itertuples()
    ]
    result["concise_reason"] = [
        _concise_reason(
            row.source_severity,
            row.materiality_status,
            row.materiality_floor_expected_count,
        )
        for row in result.itertuples()
    ]
    result["evidence_facts"] = [_evidence_facts(row) for row in result.itertuples()]
    explanation = (
        result["headline"] + " " + result["concise_reason"] + " " + result["evidence_facts"].map(" ".join)
    ).str.lower()
    if any(term in f" {text} " for text in explanation for term in NON_CAUSAL_TERMS):
        raise ValueError("operator explanation contains prohibited causal wording")
    return result


def prepare_inbox(
    entity: pd.DataFrame,
    anomalies: pd.DataFrame,
    config: SignalPrioritizationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return ranked warnings, data-quality, low-volume attention, and secondary evidence."""
    if entity.duplicated(CANONICAL_KEY).any():
        raise ValueError("duplicate entity/origin rows would create duplicate Inbox items")
    enriched = _add_anomaly_context(entity, anomalies)
    enriched["source_severity"] = enriched["severity"]
    enriched["materiality_floor_expected_count"] = config.materiality_floor_expected_count
    zero_baseline_low_volume = (
        enriched["threshold_status"].eq("supported")
        & np.isfinite(enriched["threshold_value"])
        & enriched["threshold_value"].eq(0.0)
        & np.isfinite(enriched["forecast_value"])
        & (enriched["forecast_value"] < config.materiality_floor_expected_count)
    )
    enriched["materiality_status"] = np.where(
        zero_baseline_low_volume,
        LOW_VOLUME_MATERIALITY_STATUS,
        "materiality_rule_not_triggered",
    )
    enriched["direct_supported"] = _direct_supported(enriched)
    enriched["uncertainty_available"] = _calibrated_uncertainty(enriched)
    valid_ratio = (
        enriched["threshold_status"].eq("supported")
        & np.isfinite(enriched["threshold_value"])
        & (enriched["threshold_value"] > 0)
        & np.isfinite(enriched["forecast_value"])
    )
    enriched["central_threshold_ratio_valid"] = valid_ratio
    enriched["central_threshold_ratio"] = np.where(
        valid_ratio,
        enriched["forecast_value"] / enriched["threshold_value"],
        np.nan,
    )
    enriched["priority_support_class"] = np.where(
        enriched["direct_supported"], "direct_supported", "fallback_or_limited_history"
    )

    primary = enriched[enriched["target"].eq(config.primary_target)].copy()
    unsupported_mask = primary["severity"].eq("UNSUPPORTED") | primary["threshold_status"].ne("supported")
    source_warning_mask = primary["source_severity"].isin(config.alert_severities)
    low_volume_mask = primary["materiality_status"].eq(LOW_VOLUME_MATERIALITY_STATUS) & source_warning_mask
    primary["operational_priority_status"] = "not_a_primary_warning"
    primary.loc[unsupported_mask, "operational_priority_status"] = "unsupported_data_quality"
    primary.loc[low_volume_mask, "operational_priority_status"] = LOW_VOLUME_MATERIALITY_STATUS
    eligible_mask = ~unsupported_mask & ~low_volume_mask & source_warning_mask
    primary.loc[eligible_mask, "operational_priority_status"] = "primary_inbox_eligible"
    unsupported = primary[unsupported_mask].copy()
    low_volume = primary[~unsupported_mask & low_volume_mask].copy()
    warning = primary[eligible_mask].copy()
    warning["_severity_priority"] = warning["source_severity"].map(SEVERITY_PRIORITY)
    warning["_lead_priority"] = warning["lead_time_days"].fillna(np.inf)
    warning["_support_priority"] = (~warning["direct_supported"]).astype(int)
    warning["_uncertainty_priority"] = (~warning["uncertainty_available"]).astype(int)
    warning["_ratio_valid_priority"] = (~warning["central_threshold_ratio_valid"]).astype(int)
    warning["_ratio_priority"] = warning["central_threshold_ratio"].fillna(-np.inf)
    warning = warning.sort_values(
        [
            *RANK_PARTITION,
            "_severity_priority",
            "_lead_priority",
            "_support_priority",
            "_uncertainty_priority",
            "_ratio_valid_priority",
            "_ratio_priority",
            "region_id",
            "hospital_id",
            "profile_id",
            "series_id",
        ],
        ascending=[True, True, True, True, True, True, True, True, False, True, True, True, True],
        kind="stable",
    )
    warning["inbox_rank"] = warning.groupby(RANK_PARTITION, sort=False, observed=True).cumcount() + 1
    warning = warning.drop(columns=[column for column in warning.columns if column.startswith("_")])
    warning = _add_explanations(warning)

    unsupported = unsupported.sort_values(
        [*RANK_PARTITION, "region_id", "hospital_id", "profile_id", "series_id"], kind="stable"
    )
    unsupported["data_quality_rank"] = unsupported.groupby(RANK_PARTITION, sort=False, observed=True).cumcount() + 1
    unsupported["inbox_rank"] = pd.NA
    unsupported = _add_explanations(unsupported)

    low_volume = low_volume.sort_values(
        [*RANK_PARTITION, "region_id", "hospital_id", "profile_id", "series_id"], kind="stable"
    )
    low_volume["attention_rank"] = low_volume.groupby(RANK_PARTITION, sort=False, observed=True).cumcount() + 1
    low_volume["inbox_rank"] = pd.NA
    low_volume = _add_explanations(low_volume)

    secondary = enriched[enriched["target"].eq(config.secondary_target)].copy()
    secondary["research_evidence_only"] = True
    secondary["operational_priority_status"] = "secondary_research_evidence"
    secondary["inbox_rank"] = pd.NA
    secondary = _add_explanations(secondary)
    if not np.array_equal(enriched["source_severity"].to_numpy(), entity["severity"].to_numpy()):
        raise RuntimeError("source severity changed during product materiality preparation")
    return warning, unsupported, low_volume, secondary


def observed_anomaly_view(anomalies: pd.DataFrame, entity: pd.DataFrame) -> pd.DataFrame:
    flagged = anomalies[anomalies["anomaly_status"].isin(["UNUSUAL_HIGH", "UNUSUAL_LOW"])].copy()
    pressure = entity[entity["target"].eq("registrations")][
        ["phase", "origin", "series_id", "severity", "signal_id", "first_crossing_date", "lead_time_days"]
    ].rename(
        columns={
            "origin": "forecast_origin",
            "severity": "future_pressure_severity",
            "signal_id": "future_pressure_signal_id",
        }
    )
    result = flagged.merge(pressure, on=["forecast_origin", "series_id"], how="left", validate="one_to_one")
    result["future_warning_present"] = result["future_pressure_severity"].isin(ALERT_SEVERITIES)
    return result


def inbox_views(
    ranked: pd.DataFrame,
    unsupported: pd.DataFrame,
    low_volume: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    fallback = ~ranked["direct_supported"]
    return {
        "top_priority_all": ranked.copy(),
        "high_only": ranked[ranked["severity"].eq("HIGH")].copy(),
        "watchlist_7d": ranked[ranked["any_alert_7d"]].copy(),
        "watchlist_14d": ranked[ranked["any_alert_14d"]].copy(),
        "fallback_attention": ranked[fallback].copy(),
        "unsupported_data_quality": unsupported.copy(),
        "zero_baseline_low_volume_attention": low_volume.copy(),
        "observed_anomalies": observed.copy(),
    }


def materiality_diagnostics(
    ranked: pd.DataFrame,
    low_volume: pd.DataFrame,
    config: SignalPrioritizationConfig,
) -> dict:
    before = pd.concat([ranked, low_volume], ignore_index=True)

    def composition(frame: pd.DataFrame) -> dict:
        direct = int(frame["direct_supported"].sum()) if len(frame) else 0
        fallback = int(len(frame) - direct)
        return {
            "rows": int(len(frame)),
            "direct_supported": direct,
            "fallback_or_limited_history": fallback,
            "direct_supported_share": float(direct / len(frame)) if len(frame) else None,
            "fallback_or_limited_share": float(fallback / len(frame)) if len(frame) else None,
        }

    final = ranked[ranked["phase"].eq("final_test")].head(config.demo_top_n)
    by_phase_origin = []
    partitions = before[["phase", "origin"]].drop_duplicates().sort_values(["phase", "origin"])
    for partition in partitions.itertuples(index=False):
        before_partition = before[before["phase"].eq(partition.phase) & before["origin"].eq(partition.origin)]
        after_partition = ranked[ranked["phase"].eq(partition.phase) & ranked["origin"].eq(partition.origin)]
        removed_partition = low_volume[
            low_volume["phase"].eq(partition.phase) & low_volume["origin"].eq(partition.origin)
        ]
        by_phase_origin.append(
            {
                "phase": partition.phase,
                "origin": partition.origin,
                "removed_from_primary_inbox": int(len(removed_partition)),
                "source_high_before_materiality": int(before_partition["source_severity"].eq("HIGH").sum()),
                "source_high_after_materiality": int(after_partition["source_severity"].eq("HIGH").sum()),
                "primary_inbox_composition": composition(after_partition),
            }
        )
    return {
        "materiality_floor_expected_count": config.materiality_floor_expected_count,
        "removed_from_primary_inbox": int(len(low_volume)),
        "source_high_before_materiality": int(before["source_severity"].eq("HIGH").sum()),
        "source_high_after_materiality": int(ranked["source_severity"].eq("HIGH").sum()),
        "primary_inbox_composition": composition(ranked),
        "final_test_top_20_composition": composition(final),
        "by_phase_origin": by_phase_origin,
        "optimized_from_outcomes": False,
    }


def regional_rollup(
    entity: pd.DataFrame,
    config: SignalPrioritizationConfig,
) -> pd.DataFrame:
    primary = entity[entity["target"].eq(config.primary_target)].copy()
    records = []
    for (phase, origin, region_id), part in primary.groupby(["phase", "origin", "region_id"], sort=True, observed=True):
        source_warnings = part[
            part["severity"].isin(config.alert_severities) & part["threshold_status"].eq("supported")
        ]
        low_volume = source_warnings[
            np.isfinite(source_warnings["threshold_value"])
            & source_warnings["threshold_value"].eq(0.0)
            & np.isfinite(source_warnings["forecast_value"])
            & (source_warnings["forecast_value"] < config.materiality_floor_expected_count)
        ]
        warnings = source_warnings.drop(index=low_volume.index)
        direct = _direct_supported(warnings)
        profile_records = []
        for profile_id, profile in warnings.groupby("profile_id", sort=True, observed=True):
            highest = min(profile["severity"], key=lambda value: SEVERITY_PRIORITY[value])
            profile_records.append(
                {
                    "profile_id": str(profile_id),
                    "warning_entities": int(len(profile)),
                    "highest_severity": highest,
                    "_priority": SEVERITY_PRIORITY[highest],
                }
            )
        profile_records.sort(key=lambda row: (row["_priority"], -row["warning_entities"], row["profile_id"]))
        top_profiles = [
            {key: value for key, value in row.items() if key != "_priority"}
            for row in profile_records[: config.regional_top_profiles]
        ]
        warning_count = len(warnings)
        records.append(
            {
                "phase": phase,
                "forecast_origin": origin,
                "region_id": region_id,
                "target": config.primary_target,
                "high_entities": int((warnings["severity"] == "HIGH").sum()),
                "elevated_entities": int((warnings["severity"] == "ELEVATED").sum()),
                "watch_entities": int((warnings["severity"] == "WATCH").sum()),
                "source_high_entities_before_materiality": int((source_warnings["severity"] == "HIGH").sum()),
                "zero_baseline_low_volume_attention_entities": int(len(low_volume)),
                "unsupported_entities": int(
                    (part["severity"].eq("UNSUPPORTED") | part["threshold_status"].ne("supported")).sum()
                ),
                "nearest_crossing_lead_time_days": (
                    int(warnings["lead_time_days"].min()) if warnings["lead_time_days"].notna().any() else None
                ),
                "top_affected_profiles": top_profiles,
                "warning_entities": int(warning_count),
                "direct_supported_entities": int(direct.sum()),
                "fallback_or_limited_entities": int(warning_count - direct.sum()),
                "direct_supported_share": float(direct.mean()) if warning_count else None,
                "fallback_or_limited_share": float((~direct).mean()) if warning_count else None,
            }
        )
    return pd.DataFrame(records)


def _json_records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def demo_artifacts(
    views: dict[str, pd.DataFrame],
    regional: pd.DataFrame,
    config: SignalPrioritizationConfig,
) -> dict:
    ranked = views["top_priority_all"]

    def final_first(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        final = frame[frame["phase"].eq("final_test")]
        return final if not final.empty else frame

    def one(frame: pd.DataFrame, reason: str) -> dict:
        eligible = final_first(frame)
        if eligible.empty:
            return {"available": False, "reason": reason}
        return {"available": True, "example": _json_records(eligible.iloc[[0]])[0]}

    top = final_first(ranked).head(config.demo_top_n)
    high_direct = ranked[ranked["severity"].eq("HIGH") & ranked["direct_supported"]]
    anomaly_and_warning = views["observed_anomalies"][views["observed_anomalies"]["future_warning_present"]]
    regional_examples = final_first(
        regional.sort_values(
            ["phase", "forecast_origin", "high_entities", "elevated_entities", "watch_entities", "region_id"],
            ascending=[True, True, False, False, False, True],
            kind="stable",
        )
    ).head(5)
    return {
        "top_20_inbox_examples": _json_records(top),
        "high_direct_support": one(high_direct, "no HIGH direct-support warning in source artifacts"),
        "regional_fallback": one(views["fallback_attention"], "no fallback warning in source artifacts"),
        "observed_anomaly_plus_future_warning": one(
            anomaly_and_warning, "no observed anomaly plus future warning in source artifacts"
        ),
        "unsupported_data_quality": one(
            views["unsupported_data_quality"], "no unsupported registration signal in source artifacts"
        ),
        "zero_baseline_low_volume_attention": one(
            views["zero_baseline_low_volume_attention"],
            "no supported zero-baseline low-volume warning in source artifacts",
        ),
        "regional_summary_examples": _json_records(regional_examples),
    }
