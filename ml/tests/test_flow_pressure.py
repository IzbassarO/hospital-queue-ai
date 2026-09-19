from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hqai_ml.features.load import Panel
from hqai_ml.flow_forecast.config import FlowPressureConfig
from hqai_ml.flow_forecast.pressure import (
    DAILY_ALERT_UNIT,
    ENTITY_ORIGIN_ALERT_UNIT,
    aggregate_pressure_signals,
    derive_daily_pressure_signals,
    entity_origin_warning_metrics,
    hierarchy_evaluation_key,
    historical_flow_thresholds,
    load_verified_hierarchy_forecasts,
    observed_flow_anomalies,
    representative_examples,
    retrospective_warning_metrics,
    severity_for_row,
)
from hqai_ml.registry import store
from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun, execution_metadata
from hqai_ml.registry.resources import resource_config
from pipelines.flow_pressure import pressure_protocol


def config(**updates) -> FlowPressureConfig:
    raw = {
        "schema_version": 1,
        "version": "test-pressure-v1",
        "seed": 42,
        "threshold_semantics": "historical_flow_proxy_v1",
        "compatible_future_threshold_semantics": "physical_capacity_provider_v1",
        "primary_target": "registrations",
        "secondary_target": "cohort_hospitalizations",
        "horizon": 14,
        "validation_origins": [dt.date(2025, 2, 16), dt.date(2025, 2, 23), dt.date(2025, 3, 2)],
        "final_test_origin": dt.date(2025, 3, 17),
        "severity_order": ["NORMAL", "WATCH", "ELEVATED", "HIGH"],
        "threshold": {
            "method": "origin_legal_empirical_quantile_higher",
            "quantile": 0.9,
            "history_window_days": 35,
            "minimum_date_class_observations": 3,
            "minimum_date_class_positive_days": 2,
            "minimum_pooled_observations": 14,
            "minimum_pooled_positive_days": 3,
            "fallback_ladder": [
                "hospital_date_class",
                "hospital_pooled",
                "region_date_class",
                "region_pooled",
            ],
            "event_comparison": "actual_strictly_greater_than_threshold",
        },
        "anomaly": {
            "method": "weekly_residual_median_mad",
            "target": "registrations",
            "lookback_days": 35,
            "minimum_residuals": 7,
            "robust_z_threshold": 3.5,
        },
        "automatic_promotion": False,
        "autonomous_action": False,
        "identity_sha256": "pressure-config",
    }
    raw.update(updates)
    return FlowPressureConfig(**raw)


def panels() -> tuple[Panel, Panel]:
    dates = [dt.date(2025, 1, 1) + dt.timedelta(days=index) for index in range(90)]
    h1 = np.asarray([2 + (index % 7 == 0) for index in range(90)], dtype=float)
    h2 = np.zeros(90)
    h3 = np.zeros(90)
    hospital_values = np.vstack([h1, h2, h3])
    hospital_meta = pd.DataFrame(
        [
            {
                "series_id": "hp:h1:p1",
                "level": "hospital",
                "org_code": "h1",
                "region_code": "r1",
                "profile_code": "p1",
            },
            {
                "series_id": "hp:h2:p1",
                "level": "hospital",
                "org_code": "h2",
                "region_code": "r1",
                "profile_code": "p1",
            },
            {
                "series_id": "hp:h3:p2",
                "level": "hospital",
                "org_code": "h3",
                "region_code": "r2",
                "profile_code": "p2",
            },
        ]
    )
    region_values = np.vstack([h1 + h2, h3])
    region_meta = pd.DataFrame(
        [
            {
                "series_id": "rp:r1:p1",
                "level": "region",
                "org_code": "__region__",
                "region_code": "r1",
                "profile_code": "p1",
            },
            {
                "series_id": "rp:r2:p2",
                "level": "region",
                "org_code": "__region__",
                "region_code": "r2",
                "profile_code": "p2",
            },
        ]
    )
    zeros_h = np.zeros_like(hospital_values)
    zeros_r = np.zeros_like(region_values)
    return (
        Panel(dates, hospital_meta, hospital_values, hospital_values.copy(), zeros_h),
        Panel(dates, region_meta, region_values, region_values.copy(), zeros_r),
    )


def test_thresholds_are_origin_legal_and_ignore_future_values():
    hospital, region = panels()
    origin = dt.date(2025, 2, 16)
    first = historical_flow_thresholds(hospital, region, [origin], ["registrations"], config(), set())
    changed_hospital, changed_region = panels()
    origin_index = changed_hospital.index_of(origin)
    changed_hospital.registrations[:, origin_index + 1 :] = 1_000_000
    changed_region.registrations[:, origin_index + 1 :] = 1_000_000
    second = historical_flow_thresholds(changed_hospital, changed_region, [origin], ["registrations"], config(), set())
    pd.testing.assert_frame_equal(first, second)
    assert (first["threshold_history_end"] <= first["origin"]).all()


def test_date_class_and_region_fallback_provenance_and_unsupported_state():
    hospital, region = panels()
    origin = dt.date(2025, 2, 16)
    holidays = {origin + dt.timedelta(days=2)}
    thresholds = historical_flow_thresholds(hospital, region, [origin], ["registrations"], config(), holidays)
    h1 = thresholds[thresholds["series_id"] == "hp:h1:p1"]
    holiday = h1[h1["threshold_date_class"] == "holiday"]
    assert set(holiday["threshold_fallback_level"]) == {"hospital_pooled"}
    h2 = thresholds[thresholds["series_id"] == "hp:h2:p1"]
    assert set(h2["threshold_fallback_level"]).issubset({"region_date_class", "region_pooled"})
    h3 = thresholds[thresholds["series_id"] == "hp:h3:p2"]
    assert set(h3["threshold_status"]) == {"unsupported"}
    assert set(h3["threshold_fallback_level"]) == {"unsupported_insufficient_history"}


def test_severity_ordering_and_unsupported_uncertainty():
    assert severity_for_row(9, 10, 11, 12, True)[0] == "HIGH"
    assert severity_for_row(11, 10, 5, 12, True)[0] == "ELEVATED"
    assert severity_for_row(9, 10, 5, 12, True)[0] == "WATCH"
    assert severity_for_row(9, 10, None, None, True)[0] == "NORMAL"
    assert severity_for_row(100, None, None, None, False)[0] == "UNSUPPORTED"


def forecast_rows(values: list[float], uncertainty_status: str = "level_local_calibrated") -> pd.DataFrame:
    origin = pd.Timestamp("2025-02-16")
    rows = []
    for horizon, value in enumerate(values, start=1):
        rows.append(
            {
                "phase": "validation",
                "origin": origin,
                "target": "registrations",
                "level": "hospital",
                "series_id": "hp:h1:p1",
                "horizon": horizon,
                "target_date": origin + pd.Timedelta(days=horizon),
                "org_code": "h1",
                "region_code": "r1",
                "profile_code": "p1",
                "y": 12.0 if horizon == 2 else 8.0,
                "forecast_value": value,
                "forecast_source": "direct_quantile_ml",
                "support_status": "supported",
                "fallback_status": "not_applicable",
                "uncertainty_status": uncertainty_status,
                "calibration_version": "cal-v1",
                "calibration_status": "calibrated",
                "level_local_interval_80_lower": value - 2,
                "level_local_interval_80_upper": value + 2,
            }
        )
    return pd.DataFrame(rows)


def threshold_rows(count: int, value: float = 10.0) -> pd.DataFrame:
    origin = pd.Timestamp("2025-02-16")
    return pd.DataFrame(
        [
            {
                "origin": origin,
                "target": "registrations",
                "series_id": "hp:h1:p1",
                "horizon": horizon,
                "target_date": origin + pd.Timedelta(days=horizon),
                "threshold_status": "supported",
                "threshold_value": value,
                "threshold_fallback_level": "hospital_date_class",
                "threshold_semantics": "historical_flow_proxy_v1",
            }
            for horizon in range(1, count + 1)
        ]
    )


def test_crossing_date_lead_time_and_uncertainty_unavailable_behavior():
    daily = derive_daily_pressure_signals(forecast_rows([8.0, 9.0, 11.0]), threshold_rows(3), config())
    assert daily["severity"].tolist() == ["NORMAL", "WATCH", "ELEVATED"]
    entity = aggregate_pressure_signals(daily, config()).iloc[0]
    assert entity["first_crossing_date"] == pd.Timestamp("2025-02-18")
    assert entity["lead_time_days"] == 2
    assert entity["max_severity_7d"] == "ELEVATED"

    unavailable = derive_daily_pressure_signals(
        forecast_rows([9.0], uncertainty_status="uncertainty_unavailable"), threshold_rows(1), config()
    )
    assert unavailable.iloc[0]["severity"] == "NORMAL"
    assert pd.isna(unavailable.iloc[0]["uncertainty_lower"])
    assert "UNCERTAINTY_UNAVAILABLE" in unavailable.iloc[0]["reason_codes"]


def test_entity_example_severity_is_reproducible_from_one_horizon_evidence():
    daily = derive_daily_pressure_signals(forecast_rows([11.0, 13.0]), threshold_rows(2), config())
    assert daily["severity"].tolist() == ["ELEVATED", "HIGH"]
    entity = aggregate_pressure_signals(daily, config())
    row = entity.iloc[0]
    assert row["severity"] == "HIGH"
    assert row["displayed_severity_basis"] == "max_severity_14d"
    assert row["severity_evidence_horizon"] == 2
    assert row["severity_evidence_date"] == pd.Timestamp("2025-02-18")
    assert row["first_crossing_severity"] == "ELEVATED"
    assert row["first_crossing_date"] == pd.Timestamp("2025-02-17")
    assert row["lead_time_days"] == 1

    examples = representative_examples(
        entity,
        pd.DataFrame(columns=["anomaly_status", "forecast_origin", "series_id", "severity"]),
    )
    example = examples["supported_future_warning"]["example"]
    reproduced, reason = severity_for_row(
        example["forecast_value"],
        example["threshold_value"],
        example["uncertainty_lower"],
        example["uncertainty_upper"],
        example["threshold_status"] == "supported",
    )
    assert example["target"] == "registrations"
    assert reproduced == example["severity"] == "HIGH"
    assert reason in example["reason_codes"]


def test_retrospective_event_definition_and_precision_recall_calculation():
    daily = pd.DataFrame(
        {
            "phase": "validation",
            "target": "registrations",
            "threshold_status": "supported",
            "is_alert": [True, True, False, False],
            "actual_exceeds_threshold": [True, False, True, False],
            "severity": ["HIGH", "WATCH", "NORMAL", "NORMAL"],
            "horizon": [1, 2, 3, 4],
        }
    )
    metrics = retrospective_warning_metrics(daily)[0]
    assert metrics["alert_count"] == 2
    assert metrics["event_count"] == 2
    assert metrics["precision"] == pytest.approx(0.5)
    assert metrics["recall"] == pytest.approx(0.5)
    assert metrics["false_alert_rate"] == pytest.approx(0.5)
    assert "strictly_exceeds" in metrics["event_definition"]
    assert metrics["metric_family"] == "daily_cell"
    assert metrics["alert_unit"] == DAILY_ALERT_UNIT
    assert metrics["incident_or_episode_level"] is False


def test_persistent_warning_counts_daily_cells_but_one_entity_origin():
    forecasts = forecast_rows([11.0] * 14)
    forecasts["y"] = 12.0
    daily = derive_daily_pressure_signals(forecasts, threshold_rows(14), config())
    assert set(daily["alert_unit"]) == {DAILY_ALERT_UNIT}
    daily_metrics = retrospective_warning_metrics(daily)[0]
    assert daily_metrics["alert_count"] == 14
    assert daily_metrics["event_count"] == 14
    assert daily_metrics["median_lead_time_days"] == pytest.approx(7.5)

    entity = aggregate_pressure_signals(daily, config())
    assert len(entity) == 1
    row = entity.iloc[0]
    assert row["alert_unit"] == ENTITY_ORIGIN_ALERT_UNIT
    assert bool(row["any_alert_7d"])
    assert bool(row["any_alert_14d"])
    assert row["max_severity_7d"] == "ELEVATED"
    assert row["max_severity_14d"] == "ELEVATED"
    assert row["first_crossing_date"] == pd.Timestamp("2025-02-17")
    assert row["lead_time_days"] == 1

    entity_metrics = entity_origin_warning_metrics(entity)
    fourteen_day = next(metric for metric in entity_metrics if metric["window_days"] == 14)
    assert fourteen_day["metric_family"] == "entity_origin"
    assert fourteen_day["alert_unit"] == ENTITY_ORIGIN_ALERT_UNIT
    assert fourteen_day["alert_count"] == 1
    assert fourteen_day["event_count"] == 1
    assert fourteen_day["precision"] == pytest.approx(1.0)
    assert fourteen_day["recall"] == pytest.approx(1.0)
    assert fourteen_day["incident_or_episode_level"] is False


def test_robust_anomaly_is_origin_legal_and_has_no_causal_claim():
    hospital, _ = panels()
    pattern = np.random.default_rng(42).poisson(10, size=90).astype(float)
    hospital.registrations[0] = pattern
    origin = dt.date(2025, 3, 2)
    origin_index = hospital.index_of(origin)
    hospital.registrations[0, origin_index] += 100
    first = observed_flow_anomalies(hospital, [origin], config())
    row = first[first["series_id"] == "hp:h1:p1"].iloc[0]
    assert row["anomaly_status"] == "UNUSUAL_HIGH"
    assert row["reference_max_date"] < row["forecast_origin"]
    assert row["causal_claim"] is False or not row["causal_claim"]
    hospital.registrations[:, origin_index + 1 :] = 999_999
    second = observed_flow_anomalies(hospital, [origin], config())
    pd.testing.assert_frame_equal(first, second)


def test_contract_uses_flow_pressure_not_physical_capacity_claims_and_final_never_selects():
    configured = config()
    protocol = pressure_protocol(configured)
    assert configured.threshold_semantics == "historical_flow_proxy_v1"
    assert configured.compatible_future_threshold_semantics == "physical_capacity_provider_v1"
    assert protocol["physical_capacity_used"] is False
    assert protocol["fixed_rule_no_tuning"] is True
    assert protocol["final_test_used_for_rule_selection"] is False
    with pytest.raises(ValidationError, match="cannot promote models or trigger autonomous action"):
        config(automatic_promotion=True)


def test_hierarchy_artifact_lineage_and_checksums_are_verified(tmp_path):
    resources = resource_config("smoke", cpu_count=2)
    version = "hierarchy-v1"
    evaluation_key = hierarchy_evaluation_key(version)
    evaluation_parameters = {
        "source_artifact_identity": "quantile-artifacts",
        "calibration_scientific_identity": "calibration-science",
        "configuration_identity": "hierarchy-config",
        "alternatives": ["current_direct", "bottom_up_hospital"],
        "fallback_candidates": ["current_region_profile_share", "blend"],
    }
    plan = {
        "scientific_identity_sha256": "hierarchy-science",
        "identity_sha256": "hierarchy-science",
        "scientific_identity": {"workflow": "hierarchy"},
        "models": ["load_forecast"],
        "model_families": {"load_forecast": "global_gradient_boosted_count_forecast"},
        "prediction_targets": {"load_forecast": ["registrations", "hospitalizations"]},
        "dataset": {"identity_sha256": "data"},
        "configuration": {"sha256": "config"},
        "code": {"source": {"sha256": "code"}},
        "implementation_versions": {"python": "3.12"},
        "hyperparameters": {
            "flow_hierarchy": {
                "version": version,
                "alternatives": evaluation_parameters["alternatives"],
                "fallback": {"candidates": evaluation_parameters["fallback_candidates"]},
            },
            "source_quantile": {"artifact_identity": "quantile-artifacts"},
            "source_calibration": {"scientific_identity": "calibration-science"},
        },
        "execution": execution_metadata(resources),
    }
    evaluation_artifact = tmp_path / "hierarchy-evaluation"
    evaluation_artifact.mkdir()
    pd.DataFrame(
        [
            {
                "phase": "validation",
                "origin": pd.Timestamp("2025-02-16"),
                "target": "registrations",
                "level": "hospital",
                "series_id": "hp:h1:p1",
                "horizon": 1,
                "target_date": pd.Timestamp("2025-02-17"),
                "org_code": "h1",
                "region_code": "r1",
                "profile_code": "p1",
                "y": 1.0,
                "forecast_value": 1.0,
                "forecast_source": "direct_quantile_ml",
                "hierarchy_status": "bottom_up_child_unchanged",
                "support_status": "supported",
                "fallback_status": "not_applicable",
                "uncertainty_status": "level_local_calibrated",
                "calibration_version": "cal-v1",
                "calibration_status": "calibrated",
                "level_local_interval_80_lower": 0.0,
                "level_local_interval_80_upper": 2.0,
                "hierarchy_alternative": "bottom_up_hospital",
                "fallback_candidate": "current_region_profile_share",
            }
        ]
    ).to_parquet(evaluation_artifact / "selected-central-forecast.parquet", index=False)
    evaluation_manifest = store.write_artifact_manifest(evaluation_artifact)

    summary_artifact = tmp_path / "hierarchy-summary"
    summary_artifact.mkdir()
    summary = {
        "run_id": "hierarchy-run",
        "scientific_identity_sha256": "hierarchy-science",
        "protocol": {"final_test_used_for_selection": False},
        "automatic_promotion": False,
        "analysis": {
            "hierarchy_selection": {"selected": "bottom_up_hospital"},
            "fallback_selection": {"selected": "current_region_profile_share"},
        },
    }
    (summary_artifact / "summary.json").write_text(store.canonical_json(summary), encoding="utf-8")
    summary_manifest = store.write_artifact_manifest(summary_artifact)

    run = ExperimentRun.start(tmp_path, plan, run_id="hierarchy-run")
    run.start_checkpoint(evaluation_key, parameters=evaluation_parameters)
    run.complete_checkpoint(
        evaluation_key,
        parameters=evaluation_parameters,
        metrics={},
        evaluation_status="completed",
        artifact_path=evaluation_artifact,
        artifact_sha256=evaluation_manifest["content_sha256"],
        version=version,
    )
    summary_key = CheckpointKey.model("load_forecast")
    summary_parameters = {"evaluation_checkpoint": evaluation_key.identifier}
    run.start_checkpoint(summary_key, parameters=summary_parameters)
    run.complete_checkpoint(
        summary_key,
        parameters=summary_parameters,
        metrics={},
        evaluation_status="completed",
        artifact_path=summary_artifact,
        artifact_sha256=summary_manifest["content_sha256"],
        version=version,
    )
    run.complete(
        [evaluation_key, summary_key],
        parameters_by_key={
            evaluation_key.identifier: evaluation_parameters,
            summary_key.identifier: summary_parameters,
        },
    )
    run.release_lock()

    loaded, lineage, loaded_summary = load_verified_hierarchy_forecasts(tmp_path, "hierarchy-run")
    assert len(loaded) == 1
    assert lineage["evaluation_artifact_sha256"] == evaluation_manifest["content_sha256"]
    assert loaded_summary["analysis"]["hierarchy_selection"]["selected"] == "bottom_up_hospital"
    (summary_artifact / "summary.json").write_text(json.dumps(summary | {"automatic_promotion": True}))
    with pytest.raises(store.ArtifactIntegrityError):
        load_verified_hierarchy_forecasts(tmp_path, "hierarchy-run")
