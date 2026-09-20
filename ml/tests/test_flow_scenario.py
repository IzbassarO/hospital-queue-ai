from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from hqai_ml.flow_forecast.config import FlowPressureConfig, SignalPrioritizationConfig
from hqai_ml.flow_forecast.pressure import (
    SEVERITY_RANK,
    aggregate_pressure_signals,
    derive_daily_pressure_signals,
)
from hqai_ml.flow_forecast.prioritization import prepare_inbox
from hqai_ml.flow_forecast.scenario import (
    ALLOCATION_HEURISTIC,
    EDGE_POLICY,
    PRIVATE_COMPATIBILITY_COLUMNS,
    SCENARIO_RANGE_METHOD,
    SCENARIO_RANGE_STATUS,
    BaselineProvenance,
    FlowScenarioConfig,
    ScenarioClassification,
    ScenarioContractError,
    ScenarioLever,
    ScenarioScope,
    ScenarioSpec,
    ScopeType,
    apply_scenario_levers,
    assert_baseline_reproduction,
    canonical_spec_identity,
    evaluate_scenario,
    hierarchy_coherence,
    load_flow_scenario_config,
    scenario_spec_scientific_payload,
    scenario_summary,
)


def pressure_config() -> FlowPressureConfig:
    return FlowPressureConfig(
        schema_version=1,
        version="preventive-flow-pressure-v1",
        seed=42,
        threshold_semantics="historical_flow_proxy_v1",
        compatible_future_threshold_semantics="physical_capacity_provider_v1",
        primary_target="registrations",
        secondary_target="cohort_hospitalizations",
        horizon=14,
        validation_origins=[dt.date(2025, 2, 16), dt.date(2025, 2, 23)],
        final_test_origin=dt.date(2025, 3, 17),
        severity_order=["NORMAL", "WATCH", "ELEVATED", "HIGH"],
        threshold={
            "method": "origin_legal_empirical_quantile_higher",
            "quantile": 0.9,
            "history_window_days": 56,
            "minimum_date_class_observations": 6,
            "minimum_date_class_positive_days": 2,
            "minimum_pooled_observations": 28,
            "minimum_pooled_positive_days": 3,
            "fallback_ladder": [
                "hospital_date_class",
                "hospital_pooled",
                "region_date_class",
                "region_pooled",
            ],
            "event_comparison": "actual_strictly_greater_than_threshold",
        },
        anomaly={
            "method": "weekly_residual_median_mad",
            "target": "registrations",
            "lookback_days": 56,
            "minimum_residuals": 14,
            "robust_z_threshold": 3.5,
        },
        automatic_promotion=False,
        autonomous_action=False,
    )


def prioritization_config() -> SignalPrioritizationConfig:
    return SignalPrioritizationConfig(
        schema_version=1,
        version="signals-inbox-v1",
        seed=42,
        source_signal_contract_version="preventive-flow-pressure-v1",
        source_alert_unit="hospital_profile_target_origin",
        primary_target="registrations",
        secondary_target="cohort_hospitalizations",
        materiality_floor_expected_count=1.0,
        alert_severities=["HIGH", "ELEVATED", "WATCH"],
        ranking_order=[
            "severity_desc",
            "lead_time_days_asc",
            "direct_supported_first",
            "calibrated_uncertainty_first",
            "valid_central_threshold_ratio_desc",
            "region_id_asc",
            "hospital_id_asc",
            "profile_id_asc",
            "series_id_asc",
        ],
        demo_top_n=20,
        regional_top_profiles=5,
        human_review_required=True,
        autonomous_action=False,
        automatic_promotion=False,
    )


def baseline_daily(
    *,
    missing_uncertainty: bool = False,
    unsupported: bool = False,
    horizon_scaled_interval: bool = False,
) -> pd.DataFrame:
    """Two regions, two profiles, one zero-baseline series, fourteen horizons, both targets.

    ``horizon_scaled_interval`` widens the accepted interval with the horizon so that a
    destination-derived scenario range is numerically distinguishable from a range that would
    have been transported across dates by a time shift.
    """
    origin = pd.Timestamp("2025-02-16")
    entities = [
        ("h1", "r1", "p1", 5.0),
        ("h2", "r1", "p1", 3.0),
        ("h3", "r2", "p1", 2.0),
        ("h4", "r2", "p2", 0.0),
    ]
    forecasts = []
    thresholds = []
    for target in ("registrations", "cohort_hospitalizations"):
        for hospital, region, profile, central in entities:
            for horizon in range(1, 15):
                value = central + (1.0 if hospital == "h1" and horizon == 3 else 0.0)
                half_width = 0.5 * horizon if horizon_scaled_interval else 1.0
                series_id = f"hp:{hospital}:{profile}"
                status = "uncertainty_unavailable" if missing_uncertainty else "level_local_calibrated"
                forecasts.append(
                    {
                        "phase": "validation",
                        "origin": origin,
                        "target": target,
                        "level": "hospital",
                        "series_id": series_id,
                        "horizon": horizon,
                        "target_date": origin + pd.Timedelta(days=horizon),
                        "org_code": hospital,
                        "region_code": region,
                        "profile_code": profile,
                        "y": value,
                        "forecast_value": value,
                        "forecast_source": "direct_quantile_ml",
                        "hierarchy_status": "bottom_up_child_unchanged",
                        "support_status": "supported",
                        "fallback_status": "not_applicable",
                        "uncertainty_status": status,
                        "calibration_version": "cal-v1",
                        "calibration_status": "calibrated" if not missing_uncertainty else "unavailable",
                        "level_local_interval_80_lower": max(0.0, value - half_width),
                        "level_local_interval_80_upper": value + half_width,
                        "hierarchy_alternative": "bottom_up_hospital",
                        "fallback_candidate": "current_region_profile_share",
                        "raw_p10": value - 2.0,
                        "raw_p50": value,
                        "raw_p90": value + 2.0,
                    }
                )
                threshold_supported = not (unsupported and hospital == "h1")
                thresholds.append(
                    {
                        "origin": origin,
                        "target": target,
                        "series_id": series_id,
                        "horizon": horizon,
                        "target_date": origin + pd.Timedelta(days=horizon),
                        "threshold_status": "supported" if threshold_supported else "unsupported",
                        "threshold_value": 5.5 if threshold_supported else np.nan,
                        "threshold_fallback_level": (
                            "hospital_date_class" if threshold_supported else "unsupported_insufficient_history"
                        ),
                        "threshold_semantics": "historical_flow_proxy_v1",
                    }
                )
    return derive_daily_pressure_signals(pd.DataFrame(forecasts), pd.DataFrame(thresholds), pressure_config())


def anomalies() -> pd.DataFrame:
    return pd.DataFrame(columns=["forecast_origin", "series_id", "anomaly_status"])


def spec(
    scenario_type: str = "identity",
    *,
    classification: ScenarioClassification = ScenarioClassification.SAFE_NON_CAUSAL_STRESS_TEST,
    scope: ScenarioScope | None = None,
    parameters: dict | None = None,
) -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id=f"test-{scenario_type}",
        scenario_version="forecast-stress-test-v1",
        scenario_type=scenario_type,
        classification=classification,
        baseline_provenance=BaselineProvenance(
            hierarchy_run_id="hierarchy",
            pressure_run_id="pressure",
            prioritization_run_id="priority",
        ),
        scope=scope or ScenarioScope(),
        parameters=parameters or {},
        created_at=dt.datetime(2026, 9, 19, tzinfo=dt.UTC),
    )


def test_identity_and_multiplier_one_reproduce_baseline_scientific_fields():
    daily = baseline_daily()
    baseline_entity = aggregate_pressure_signals(daily, pressure_config())
    baseline_inbox, baseline_unsupported, baseline_low_volume, _ = prepare_inbox(
        baseline_entity, anomalies(), prioritization_config()
    )
    for scenario in (spec(), spec("demand_multiplier", parameters={"multiplier": 1.0})):
        result = evaluate_scenario(daily, anomalies(), pressure_config(), prioritization_config(), scenario)
        reproduction = assert_baseline_reproduction(
            result.daily_cells,
            daily,
            result.entity_signals,
            baseline_entity,
            result.inbox,
            baseline_inbox,
            result.unsupported,
            baseline_unsupported,
            result.low_volume_attention,
            baseline_low_volume,
        )
        assert reproduction["status"] == "PASS"


def test_demand_multiplier_is_monotonic_and_severity_cannot_decrease():
    daily = baseline_daily()
    result = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.2}),
    )
    registrations = result.daily_cells["target"].eq("registrations")
    assert (
        result.daily_cells.loc[registrations, "scenario_central"] >= daily.loc[registrations, "forecast_value"]
    ).all()
    baseline_rank = daily.loc[registrations, "severity"].map(SEVERITY_RANK).to_numpy()
    scenario_rank = result.daily_cells.loc[registrations, "severity"].map(SEVERITY_RANK).to_numpy()
    assert (scenario_rank >= baseline_rank).all()


def test_unsupported_threshold_stays_unsupported_and_missing_range_never_creates_watch_or_high():
    unsupported_daily = baseline_daily(unsupported=True)
    result = evaluate_scenario(
        unsupported_daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 10.0}),
    )
    h1 = result.daily_cells["hospital_id"].eq("h1")
    assert set(result.daily_cells.loc[h1, "severity"]) == {"UNSUPPORTED"}

    unavailable = baseline_daily(missing_uncertainty=True)
    result = evaluate_scenario(
        unavailable,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.0}),
    )
    assert not result.daily_cells["severity"].isin(["WATCH", "HIGH"]).any()


def test_transfer_conserves_profile_date_and_rejects_cross_profile_and_bad_fraction():
    daily = baseline_daily()
    scope = ScenarioScope(scope_type=ScopeType.PROFILE, profile_id="p1")
    transfer = spec(
        "inflow_transfer",
        classification=ScenarioClassification.MECHANISTIC_ACCOUNTING_SCENARIO,
        scope=scope,
        parameters={"source_hospital_id": "h1", "destination_hospital_id": "h3", "fraction": 0.25},
    )
    transformed, metadata = apply_scenario_levers(daily, transfer)
    before = (
        daily[(daily["target"] == "registrations") & (daily["profile_id"] == "p1")]
        .groupby("target_date")["forecast_value"]
        .sum()
    )
    after = (
        transformed[(transformed["target"] == "registrations") & (transformed["profile_id"] == "p1")]
        .groupby("target_date")["scenario_central"]
        .sum()
    )
    np.testing.assert_allclose(before, after, atol=1e-9, rtol=0)
    assert metadata[0]["feasibility"] == "UNKNOWN"
    assert metadata[0]["capacity_checked"] is False

    with pytest.raises(ValueError, match="cannot cross profiles"):
        apply_scenario_levers(
            daily,
            spec(
                "inflow_transfer",
                classification=ScenarioClassification.MECHANISTIC_ACCOUNTING_SCENARIO,
                scope=scope,
                parameters={
                    "source_hospital_id": "h1",
                    "destination_hospital_id": "h3",
                    "fraction": 0.2,
                    "destination_profile_id": "p2",
                },
            ),
        )
    for fraction in (-0.01, 1.01):
        with pytest.raises(ValueError, match=r"\[0,1\]"):
            apply_scenario_levers(
                daily,
                spec(
                    "inflow_transfer",
                    classification=ScenarioClassification.MECHANISTIC_ACCOUNTING_SCENARIO,
                    scope=scope,
                    parameters={
                        "source_hospital_id": "h1",
                        "destination_hospital_id": "h3",
                        "fraction": fraction,
                    },
                ),
            )


def test_exact_bottom_up_hierarchy_and_no_parent_uncertainty():
    result = evaluate_scenario(
        baseline_daily(),
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.1}),
    )
    coherence = hierarchy_coherence(result.hierarchy_cells)
    assert coherence == {
        "region_max_absolute_error": 0.0,
        "national_max_absolute_error": 0.0,
        "within_tolerance": True,
    }
    parents = result.hierarchy_cells["hierarchy_level"].isin(["region", "national"])
    assert set(result.hierarchy_cells.loc[parents, "hierarchy_uncertainty_status"]) == {"NOT_SCENARIO_ADJUSTED"}
    assert result.hierarchy_cells.loc[parents, "scenario_sensitivity_lower"].isna().all()


def test_inputs_support_anomaly_and_secondary_target_are_immutable():
    daily = baseline_daily()
    daily_before = daily.copy(deep=True)
    anomaly = pd.DataFrame(
        [{"forecast_origin": pd.Timestamp("2025-02-16"), "series_id": "hp:h1:p1", "anomaly_status": "UNUSUAL_HIGH"}]
    )
    anomaly_before = anomaly.copy(deep=True)
    result = evaluate_scenario(
        daily,
        anomaly,
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.2}),
    )
    pd.testing.assert_frame_equal(daily, daily_before)
    pd.testing.assert_frame_equal(anomaly, anomaly_before)
    for column in ("support_status", "fallback_status", "forecast_source"):
        assert result.daily_cells[column].equals(daily[column])
    assert result.inbox.loc[result.inbox["hospital_id"].eq("h1"), "observed_anomaly_present"].all()
    secondary = result.daily_cells["target"].eq("cohort_hospitalizations")
    np.testing.assert_array_equal(
        result.daily_cells.loc[secondary, "scenario_central"], result.daily_cells.loc[secondary, "baseline_central"]
    )


def test_relative_delta_is_null_for_zero_baseline_and_time_shift_edges_are_explicit():
    daily = baseline_daily()
    shifted = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec(
            "time_shift",
            scope=ScenarioScope(scope_type=ScopeType.HOSPITAL_PROFILE, hospital_id="h1", profile_id="p1"),
            parameters={"days": 2},
        ),
    )
    zero = shifted.daily_differences["baseline_central"].eq(0)
    assert shifted.daily_differences.loc[zero, "relative_delta"].isna().all()
    lever = shifted.metadata["levers"][0]
    assert lever["edge_mass_lost"] > 0
    assert lever["edge_mass_gained"] == 0
    assert lever["edge_handling"] == EDGE_POLICY


def test_deterministic_identity_and_scientific_hash():
    daily = baseline_daily()
    scenario = spec("demand_multiplier", parameters={"multiplier": 1.1})
    first = evaluate_scenario(daily, anomalies(), pressure_config(), prioritization_config(), scenario)
    second = evaluate_scenario(daily, anomalies(), pressure_config(), prioritization_config(), scenario)
    assert first.validation["scientific_output_sha256"] == second.validation["scientific_output_sha256"]
    assert canonical_spec_identity(scenario) == canonical_spec_identity(scenario.model_copy(deep=True))
    assert ScenarioSpec(**scenario.model_dump(mode="json")) == scenario
    pd.testing.assert_frame_equal(first.daily_cells, second.daily_cells)


@pytest.mark.parametrize(
    ("lever_type", "classification"),
    [
        ("bed_capacity", ScenarioClassification.REQUIRES_MISSING_CAPACITY_DATA),
        ("staffing", ScenarioClassification.REQUIRES_MISSING_CAPACITY_DATA),
        ("causal_rerouting", ScenarioClassification.REQUIRES_CAUSAL_IDENTIFICATION),
        ("monte_carlo", ScenarioClassification.NOT_SUPPORTED),
    ],
)
def test_unsupported_levers_fail_explicitly(lever_type, classification):
    with pytest.raises(ScenarioContractError) as error:
        apply_scenario_levers(baseline_daily(), spec(lever_type, classification=classification))
    assert error.value.code == "LEVER_UNSUPPORTED"
    assert error.value.as_dict()["reason"]


def test_scenario_uncertainty_is_labelled_non_calibrated_and_raw_quantiles_untouched():
    daily = baseline_daily()
    raw = daily[["raw_p10", "raw_p50", "raw_p90"]].copy()
    result = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.2}),
    )
    registrations = result.daily_cells["target"].eq("registrations")
    secondary = result.daily_cells["target"].eq("cohort_hospitalizations")
    assert set(result.daily_cells.loc[registrations, "scenario_uncertainty_status"]) == {SCENARIO_RANGE_STATUS}
    assert set(result.daily_cells.loc[secondary, "scenario_uncertainty_status"]) == {"NOT_SCENARIO_ADJUSTED"}
    assert set(result.daily_cells["scenario_uncertainty_method"]) == {SCENARIO_RANGE_METHOD}
    assert not result.daily_cells["scenario_range_coverage_guarantee"].any()
    pd.testing.assert_frame_equal(result.daily_cells[["raw_p10", "raw_p50", "raw_p90"]], raw)
    assert all("no coverage guarantee" in facts[-1] for facts in result.inbox["evidence_facts"])


def test_time_shift_requires_an_integer_day_count():
    with pytest.raises(ValueError, match="integer"):
        apply_scenario_levers(baseline_daily(), spec("time_shift", parameters={"days": 1.5}))


def test_scope_filters_and_lever_parameters_are_never_silently_ignored():
    with pytest.raises(ValueError, match="ignored filters"):
        ScenarioScope(scope_type=ScopeType.PROFILE, profile_id="p1", hospital_id="h1")
    with pytest.raises(ValueError, match="ignored/unknown parameters"):
        apply_scenario_levers(
            baseline_daily(),
            spec("demand_multiplier", parameters={"multiplier": 1.1, "bed_count": 10}),
        )


def test_parent_scoped_heuristic_preserves_requested_change_and_zero_children_fail():
    daily = baseline_daily()
    scope = ScenarioScope(scope_type=ScopeType.REGION_PROFILE, region_id="r1", profile_id="p1")
    transformed, metadata = apply_scenario_levers(
        daily,
        spec("profile_surge", scope=scope, parameters={"multiplier": 1.2}),
    )
    selected = daily["target"].eq("registrations") & daily["region_id"].eq("r1") & daily["profile_id"].eq("p1")
    assert transformed.loc[selected, "scenario_central"].sum() == pytest.approx(
        daily.loc[selected, "forecast_value"].sum() * 1.2
    )
    assert metadata[0]["allocation_method"] == ALLOCATION_HEURISTIC
    assert metadata[0]["allocation_is_heuristic"] is True

    zero_scope = ScenarioScope(scope_type=ScopeType.PROFILE, profile_id="p2")
    with pytest.raises(ScenarioContractError) as error:
        apply_scenario_levers(
            daily,
            spec("demand_multiplier", scope=zero_scope, parameters={"multiplier": 1.2}),
        )
    assert error.value.code == "ALLOCATION_WITHOUT_SUPPORT"


def test_scope_invariance_and_fixed_lexicographic_ranking_has_no_score():
    daily = baseline_daily()
    result = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec(
            "demand_multiplier",
            scope=ScenarioScope(scope_type=ScopeType.HOSPITAL_PROFILE, hospital_id="h1", profile_id="p1"),
            parameters={"multiplier": 1.2},
        ),
    )
    outside = ~(
        result.daily_cells["target"].eq("registrations")
        & result.daily_cells["hospital_id"].eq("h1")
        & result.daily_cells["profile_id"].eq("p1")
    )
    np.testing.assert_array_equal(
        result.daily_cells.loc[outside, "scenario_central"], result.daily_cells.loc[outside, "baseline_central"]
    )
    assert result.metadata["ranking_method"] == "fixed_lexicographic_no_learned_or_weighted_score"
    assert not any("score" in column.lower() for column in result.inbox.columns)


# --------------------------------------------------------------------------- P1-1 source reason codes


def test_reason_codes_preserve_the_accepted_source_reason_and_never_a_severity_label():
    daily = baseline_daily()
    severities = set(SEVERITY_RANK)
    for multiplier, expected_reason in (
        (1.0, "CENTRAL_FORECAST_EXCEEDS_HISTORICAL_FLOW_THRESHOLD"),
        (1.2, "CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD"),
    ):
        result = evaluate_scenario(
            daily,
            anomalies(),
            pressure_config(),
            prioritization_config(),
            spec("demand_multiplier", parameters={"multiplier": multiplier}),
        )
        cells = result.daily_cells
        registrations = cells["target"].eq("registrations")
        # The severity label must never masquerade as the source reason code.
        assert not set(cells["source_reason_code"]) & severities
        assert (cells.loc[registrations, "source_reason_code"] == cells.loc[registrations, "reason_codes"].str[0]).all()
        evidence = registrations & cells["hospital_id"].eq("h1") & cells["horizon"].eq(3)
        assert cells.loc[evidence, "source_reason_code"].tolist() == [expected_reason]
        # Cohort context keeps its accepted baseline reason codes verbatim.
        cohort = cells["target"].eq("cohort_hospitalizations")
        assert cells.loc[cohort, "reason_codes"].tolist() == daily.loc[cohort, "reason_codes"].tolist()


def test_missing_uncertainty_emits_the_documented_scenario_range_reason_code():
    result = evaluate_scenario(
        baseline_daily(missing_uncertainty=True),
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.2}),
    )
    registrations = result.daily_cells["target"].eq("registrations")
    codes = result.daily_cells.loc[registrations, "reason_codes"]
    assert all("SCENARIO_SENSITIVITY_RANGE_UNAVAILABLE" in entry for entry in codes)
    assert not result.daily_cells.loc[registrations, "severity"].isin(["WATCH", "HIGH"]).any()


def test_identity_gate_detects_a_corrupted_source_reason_or_central_value():
    daily = baseline_daily()
    baseline_entity = aggregate_pressure_signals(daily, pressure_config())
    baseline_inbox, _, _, _ = prepare_inbox(baseline_entity, anomalies(), prioritization_config())
    result = evaluate_scenario(daily, anomalies(), pressure_config(), prioritization_config(), spec())

    def gate(cells: pd.DataFrame) -> None:
        assert_baseline_reproduction(cells, daily, result.entity_signals, baseline_entity, result.inbox, baseline_inbox)

    gate(result.daily_cells)
    corrupted_reason = result.daily_cells.copy()
    corrupted_reason.loc[corrupted_reason.index[0], "source_reason_code"] = "ELEVATED"
    with pytest.raises(ScenarioContractError) as reason_error:
        gate(corrupted_reason)
    assert reason_error.value.code == "BASELINE_REPRODUCTION_FAILED"
    assert "source_reason_code" in reason_error.value.reason

    corrupted_central = result.daily_cells.copy()
    corrupted_central.loc[corrupted_central.index[0], "scenario_central"] += 0.5
    with pytest.raises(ScenarioContractError) as central_error:
        gate(corrupted_central)
    assert central_error.value.code == "BASELINE_REPRODUCTION_FAILED"
    assert "scenario_central" in central_error.value.reason


def test_identity_gate_compares_central_range_severity_and_rank_fields():
    daily = baseline_daily()
    baseline_entity = aggregate_pressure_signals(daily, pressure_config())
    baseline_inbox, baseline_unsupported, baseline_low_volume, _ = prepare_inbox(
        baseline_entity, anomalies(), prioritization_config()
    )
    result = evaluate_scenario(daily, anomalies(), pressure_config(), prioritization_config(), spec())
    report = assert_baseline_reproduction(
        result.daily_cells,
        daily,
        result.entity_signals,
        baseline_entity,
        result.inbox,
        baseline_inbox,
        result.unsupported,
        baseline_unsupported,
        result.low_volume_attention,
        baseline_low_volume,
    )
    assert report["status"] == "PASS"
    assert set(report["compared_fields"]) == {"daily", "entity", "inbox", "unsupported", "low_volume"}
    for required in ("scenario_central", "scenario_sensitivity_lower", "severity", "source_reason_code"):
        assert required in report["compared_fields"]["daily"]
    for required in ("first_crossing_severity", "any_alert_7d", "any_alert_14d", "severity_evidence_date"):
        assert required in report["compared_fields"]["entity"]
    assert "priority_support_class" in report["compared_fields"]["inbox"]


# --------------------------------------------------------------------------- P1-2 per-target summaries


def test_summary_is_per_target_and_cohort_rows_cannot_dilute_the_registrations_denominator():
    daily = baseline_daily()
    result = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.2}),
    )
    summary = scenario_summary(result)
    assert summary["primary_target"] == "registrations"
    assert not {"daily_cells", "entities", "primary_inbox"} & set(summary)

    registrations = summary["targets"]["registrations"]
    cohort = summary["targets"]["cohort_hospitalizations"]
    differences = result.daily_differences
    registration_rows = differences[differences["target"].eq("registrations")]
    assert registrations["daily_cells"]["total"] == len(registration_rows)
    assert registrations["daily_cells"]["total"] * 2 == len(differences)
    expected_share = registration_rows["severity_changed"].mean()
    assert registrations["daily_cells"]["severity_changed_share"] == pytest.approx(expected_share)
    # The pooled denominator would have halved the measured effect.
    assert registrations["daily_cells"]["severity_changed_share"] == pytest.approx(
        2 * differences["severity_changed"].mean()
    )
    assert cohort["scenario_adjustment"] == "NONE"
    assert cohort["semantic_role"] == "UNCHANGED_SECONDARY_CONTEXT"
    assert cohort["severity_changed_count"] == 0
    assert cohort["row_count"] == registrations["daily_cells"]["total"]

    entities = registrations["entities"]
    assert entities["total"] == int(result.entity_differences["target"].eq("registrations").sum())
    assert set(entities["severity_counts"]) <= set(SEVERITY_RANK)
    inbox = registrations["inbox"]
    assert inbox["scenario_size"] == len(result.inbox)
    assert inbox["baseline_size"] == len(result.baseline_inbox)
    assert inbox["direct_supported"] + inbox["fallback_limited"] == inbox["scenario_size"]


# --------------------------------------------------------------------------- P1-3 uncertainty vocabulary


def test_additive_central_shift_produces_the_documented_sensitivity_values():
    daily = baseline_daily()
    result = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.2}),
    )
    cells = result.daily_cells
    evidence = cells["target"].eq("registrations") & cells["hospital_id"].eq("h1") & cells["horizon"].eq(3)
    row = cells.loc[evidence].iloc[0]
    # baseline central 6.0, baseline range [5.0, 7.0], scenario central 7.2 -> delta 1.2
    assert row["baseline_central"] == pytest.approx(6.0)
    assert row["baseline_uncertainty_lower"] == pytest.approx(5.0)
    assert row["baseline_uncertainty_upper"] == pytest.approx(7.0)
    assert row["scenario_central"] == pytest.approx(7.2)
    assert row["scenario_sensitivity_lower"] == pytest.approx(6.2)
    assert row["scenario_sensitivity_upper"] == pytest.approx(8.2)
    assert row["scenario_uncertainty_method"] == SCENARIO_RANGE_METHOD


def test_sensitivity_lower_bound_is_floored_at_zero_and_never_crosses_the_upper_bound():
    result = evaluate_scenario(
        baseline_daily(),
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 0.0}),
    )
    registrations = result.daily_cells["target"].eq("registrations")
    lower = result.daily_cells.loc[registrations, "scenario_sensitivity_lower"]
    upper = result.daily_cells.loc[registrations, "scenario_sensitivity_upper"]
    assert (lower >= 0).all()
    assert (upper >= lower).all()
    assert not result.daily_cells.loc[registrations, "severity"].isin(["HIGH"]).any()


def test_published_scenario_artifacts_use_scenario_field_names_and_no_calibrated_claim():
    result = evaluate_scenario(
        baseline_daily(),
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.1}),
    )
    published = {
        "daily_cells": result.daily_cells,
        "entity_signals": result.entity_signals,
        "inbox": result.inbox,
        "unsupported": result.unsupported,
        "low_volume_attention": result.low_volume_attention,
        "secondary_context": result.secondary_context,
        "hierarchy_cells": result.hierarchy_cells,
    }
    for name, frame in published.items():
        leaked = sorted(set(PRIVATE_COMPATIBILITY_COLUMNS) & set(frame.columns))
        assert leaked == [], f"{name} leaked private pressure compatibility columns {leaked}"
    for name, frame in published.items():
        for column in frame.columns:
            lowered = column.lower()
            assert "confidence" not in lowered, f"{name}.{column}"
            assert not lowered.startswith("calibrated_"), f"{name}.{column}"
            if lowered.startswith("scenario_"):
                assert "calibrated" not in lowered or lowered == "scenario_calibration_status", f"{name}.{column}"
    cells = result.daily_cells
    registrations = cells["target"].eq("registrations")
    assert set(cells.loc[registrations, "scenario_uncertainty_status"]) == {SCENARIO_RANGE_STATUS}
    assert set(cells.loc[registrations, "scenario_calibration_status"]) == {"baseline_only_not_scenario"}
    assert not cells["scenario_range_coverage_guarantee"].any()
    assert set(cells["scenario_range_semantics"]) == {"derived_sensitivity_range_not_recalibrated"}
    assert result.metadata["uncertainty"]["recalibrated"] is False
    assert result.metadata["uncertainty"]["coverage_guarantee"] is False


def test_accepted_baseline_calibration_evidence_stays_baseline_labelled_and_unchanged():
    daily = baseline_daily()
    result = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.2}),
    )
    cells = result.daily_cells.sort_values(["target", "series_id", "horizon"]).reset_index(drop=True)
    accepted = daily.sort_values(["target", "series_id", "horizon"]).reset_index(drop=True)
    np.testing.assert_allclose(
        cells["baseline_uncertainty_lower"].to_numpy(float),
        accepted["uncertainty_lower"].to_numpy(float),
        equal_nan=True,
    )
    np.testing.assert_allclose(
        cells["baseline_uncertainty_upper"].to_numpy(float),
        accepted["uncertainty_upper"].to_numpy(float),
        equal_nan=True,
    )
    assert cells["baseline_uncertainty_status"].equals(accepted["uncertainty_status"])
    assert cells["baseline_calibration_version"].equals(accepted["calibration_version"])
    # A scenario-shifted cell must not equal its untouched accepted evidence.
    evidence = cells["target"].eq("registrations") & cells["hospital_id"].eq("h1") & cells["horizon"].eq(3)
    assert cells.loc[evidence, "scenario_sensitivity_lower"].iloc[0] != pytest.approx(
        cells.loc[evidence, "baseline_uncertainty_lower"].iloc[0]
    )


def _scenario_explanation_text(frame: pd.DataFrame) -> list[str]:
    """Operator-facing scenario explanation text only; baseline metadata columns are excluded."""
    text: list[str] = []
    for column in ("headline", "concise_reason"):
        if column in frame.columns:
            text.extend(frame[column].astype(str).tolist())
    if "evidence_facts" in frame.columns:
        for facts in frame["evidence_facts"]:
            text.extend(str(fact) for fact in facts)
    return text


def test_watch_and_high_explanations_never_describe_a_transformed_bound_as_calibrated():
    daily = baseline_daily()
    # x0.90 pushes the scenario central below the threshold while the transformed upper bound still
    # exceeds it, which is the only path that reaches a WATCH Inbox row.
    watch = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 0.9}),
    )
    assert (watch.inbox["source_severity"] == "WATCH").any(), "fixture no longer produces a WATCH Inbox row"
    watch_reasons = watch.inbox.loc[watch.inbox["source_severity"].eq("WATCH"), "concise_reason"]
    assert all("Derived scenario sensitivity upper bound" in reason for reason in watch_reasons)

    high = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.2}),
    )
    assert (high.inbox["source_severity"] == "HIGH").any(), "fixture no longer produces a HIGH Inbox row"
    high_reasons = high.inbox.loc[high.inbox["source_severity"].eq("HIGH"), "concise_reason"]
    assert all("Derived scenario sensitivity lower bound" in reason for reason in high_reasons)

    for result in (watch, high):
        for view in ("inbox", "unsupported", "low_volume_attention"):
            for entry in _scenario_explanation_text(getattr(result, view)):
                lowered = entry.lower()
                assert "calibrated upper forecast bound" not in lowered, f"{view}: {entry}"
                assert "calibrated lower forecast bound" not in lowered, f"{view}: {entry}"
                assert "confidence interval" not in lowered, f"{view}: {entry}"
                assert "80% interval" not in lowered, f"{view}: {entry}"
                # "calibrated" may survive only inside the explicit non-recalibration disclaimer.
                residual = lowered.replace("it is not re-calibrated", "")
                assert "calibrated" not in residual, f"{view}: {entry}"


# --------------------------------------------------------------------------- P1-4 composite and time shift


def test_composite_specs_cannot_execute_in_v1():
    composite = ScenarioSpec(
        scenario_id="composite-attempt",
        scenario_version="forecast-stress-test-v1",
        scenario_type="composite",
        classification=ScenarioClassification.NOT_SUPPORTED,
        baseline_provenance=BaselineProvenance(
            hierarchy_run_id="hierarchy", pressure_run_id="pressure", prioritization_run_id="priority"
        ),
        parameters={},
        levers=[
            ScenarioLever(
                lever_type="demand_multiplier",
                classification=ScenarioClassification.SAFE_NON_CAUSAL_STRESS_TEST,
                parameters={"multiplier": 1.5},
            ),
            ScenarioLever(
                lever_type="inflow_transfer",
                classification=ScenarioClassification.MECHANISTIC_ACCOUNTING_SCENARIO,
                scope=ScenarioScope(scope_type=ScopeType.PROFILE, profile_id="p1"),
                parameters={
                    "source_hospital_id": "h1",
                    "destination_hospital_id": "h2",
                    "fraction": 0.5,
                },
            ),
        ],
        created_at=dt.datetime(2026, 9, 19, tzinfo=dt.UTC),
    )
    for call in (
        lambda: apply_scenario_levers(baseline_daily(), composite),
        lambda: evaluate_scenario(baseline_daily(), anomalies(), pressure_config(), prioritization_config(), composite),
    ):
        with pytest.raises(ScenarioContractError) as error:
            call()
        assert error.value.code == "COMPOSITE_NOT_SUPPORTED_V1"
    # A non-composite spec cannot smuggle a second ordered lever past construction either.
    with pytest.raises(ValidationError, match="redundant normalized lever"):
        ScenarioSpec(
            **{
                **composite.model_dump(mode="json"),
                "scenario_type": "demand_multiplier",
                "classification": "SAFE_NON_CAUSAL_STRESS_TEST",
            }
        )


def test_time_shift_derives_destination_ranges_and_never_transports_uncertainty_across_dates():
    daily = baseline_daily(horizon_scaled_interval=True)
    scope = ScenarioScope(scope_type=ScopeType.HOSPITAL_PROFILE, hospital_id="h1", profile_id="p1")
    result = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("time_shift", scope=scope, parameters={"days": 1}),
    )
    cells = result.daily_cells
    selected = cells["target"].eq("registrations") & cells["hospital_id"].eq("h1")
    destination = cells.loc[selected & cells["horizon"].eq(4)].iloc[0]
    source = cells.loc[selected & cells["horizon"].eq(3)].iloc[0]
    # Horizon 3 central (6.0) is delayed into horizon 4, whose own baseline central is 5.0.
    assert destination["scenario_central"] == pytest.approx(6.0)
    assert destination["baseline_central"] == pytest.approx(5.0)
    delta = destination["scenario_central"] - destination["baseline_central"]
    assert destination["scenario_sensitivity_lower"] == pytest.approx(destination["baseline_uncertainty_lower"] + delta)
    assert destination["scenario_sensitivity_upper"] == pytest.approx(destination["baseline_uncertainty_upper"] + delta)
    # The widths differ by horizon, so a transported source range would be numerically detectable.
    destination_width = destination["scenario_sensitivity_upper"] - destination["scenario_sensitivity_lower"]
    source_width = source["baseline_uncertainty_upper"] - source["baseline_uncertainty_lower"]
    assert destination_width == pytest.approx(
        destination["baseline_uncertainty_upper"] - destination["baseline_uncertainty_lower"]
    )
    assert destination_width != pytest.approx(source_width)


def test_negative_time_shift_advances_flow_and_positive_delays_it():
    daily = baseline_daily()
    scope = ScenarioScope(scope_type=ScopeType.HOSPITAL_PROFILE, hospital_id="h1", profile_id="p1")
    advanced, advance_metadata = apply_scenario_levers(daily, spec("time_shift", scope=scope, parameters={"days": -1}))
    delayed, delay_metadata = apply_scenario_levers(daily, spec("time_shift", scope=scope, parameters={"days": 1}))
    assert advance_metadata[0]["direction"] == "advance"
    assert delay_metadata[0]["direction"] == "delay"
    selected = advanced["target"].eq("registrations") & advanced["hospital_id"].eq("h1")
    # The horizon-3 peak moves down to horizon 2 when advanced and up to horizon 4 when delayed.
    assert advanced.loc[selected & advanced["horizon"].eq(2), "scenario_central"].iloc[0] == pytest.approx(6.0)
    assert delayed.loc[selected & delayed["horizon"].eq(4), "scenario_central"].iloc[0] == pytest.approx(6.0)
    # Advancing drops the first horizon off the window; delaying drops the last.
    assert advance_metadata[0]["edge_mass_lost"] == pytest.approx(5.0)
    assert delay_metadata[0]["edge_mass_lost"] == pytest.approx(5.0)
    assert advance_metadata[0]["edge_mass_gained"] == 0
    assert advanced.loc[selected & advanced["horizon"].eq(14), "scenario_central"].iloc[0] == pytest.approx(0.0)
    assert delayed.loc[selected & delayed["horizon"].eq(1), "scenario_central"].iloc[0] == pytest.approx(0.0)


@pytest.mark.parametrize("days", [14, -14, 20, -20])
def test_oversized_time_shift_is_rejected_instead_of_zeroing_the_scenario(days):
    with pytest.raises(ScenarioContractError) as error:
        apply_scenario_levers(baseline_daily(), spec("time_shift", parameters={"days": days}))
    assert error.value.code == "INVALID_TIME_SHIFT"


def test_largest_valid_time_shifts_are_accepted_at_the_window_boundary():
    daily = baseline_daily()
    for days in (13, -13):
        transformed, metadata = apply_scenario_levers(daily, spec("time_shift", parameters={"days": days}))
        assert metadata[0]["days"] == days
        registrations = transformed["target"].eq("registrations")
        assert transformed.loc[registrations, "scenario_central"].sum() > 0


# --------------------------------------------------------------------------- P2 hardening


@pytest.mark.parametrize("value", [True, False])
def test_boolean_multipliers_and_fractions_are_rejected(value):
    with pytest.raises(ScenarioContractError) as multiplier_error:
        apply_scenario_levers(baseline_daily(), spec("demand_multiplier", parameters={"multiplier": value}))
    assert multiplier_error.value.code == "INVALID_MULTIPLIER"
    with pytest.raises(ScenarioContractError) as fraction_error:
        apply_scenario_levers(
            baseline_daily(),
            spec(
                "inflow_transfer",
                classification=ScenarioClassification.MECHANISTIC_ACCOUNTING_SCENARIO,
                scope=ScenarioScope(scope_type=ScopeType.PROFILE, profile_id="p1"),
                parameters={
                    "source_hospital_id": "h1",
                    "destination_hospital_id": "h3",
                    "fraction": value,
                },
            ),
        )
    assert fraction_error.value.code == "INVALID_TRANSFER_FRACTION"


def test_transfer_alignment_is_order_independent():
    daily = baseline_daily()
    shuffled = daily.sample(frac=1.0, random_state=7).reset_index(drop=True)
    transfer = spec(
        "inflow_transfer",
        classification=ScenarioClassification.MECHANISTIC_ACCOUNTING_SCENARIO,
        scope=ScenarioScope(scope_type=ScopeType.PROFILE, profile_id="p1"),
        parameters={"source_hospital_id": "h1", "destination_hospital_id": "h3", "fraction": 0.25},
    )
    ordered, ordered_metadata = apply_scenario_levers(daily, transfer)
    unordered, unordered_metadata = apply_scenario_levers(shuffled, transfer)
    assert ordered_metadata[0]["transferred_total"] == pytest.approx(unordered_metadata[0]["transferred_total"])
    assert unordered_metadata[0]["conservation_error"] <= 1e-9
    keys = ["target", "series_id", "horizon"]
    left = ordered.sort_values(keys).reset_index(drop=True)
    right = unordered.sort_values(keys).reset_index(drop=True)
    np.testing.assert_allclose(left["scenario_central"], right["scenario_central"])


def test_created_at_is_audit_metadata_and_never_changes_scientific_identity():
    first = spec("demand_multiplier", parameters={"multiplier": 1.1})
    later = ScenarioSpec(**{**first.model_dump(mode="json"), "levers": [], "created_at": "2027-01-31T08:45:00Z"})
    assert later.created_at != first.created_at
    assert canonical_spec_identity(later) == canonical_spec_identity(first)
    assert "created_at" not in scenario_spec_scientific_payload(first)
    # A genuine scientific change must still move the identity.
    changed = ScenarioSpec(**{**first.model_dump(mode="json"), "levers": [], "parameters": {"multiplier": 1.2}})
    assert canonical_spec_identity(changed) != canonical_spec_identity(first)


def test_shipped_config_matches_the_reviewed_stress_levels_and_drift_is_rejected():
    path = Path(__file__).resolve().parents[1] / "configs" / "flow_scenario.yaml"
    config = load_flow_scenario_config(path)
    assert config.target == "registrations"
    assert config.default_demand_stress_levels == [0.9, 1.1, 1.2]
    assert config.coverage_guarantee is False
    multipliers = [
        item.parameters["multiplier"] for item in config.standard_scenarios if item.scenario_type == "demand_multiplier"
    ]
    assert multipliers == config.default_demand_stress_levels
    assert [item.scenario_type for item in config.standard_scenarios][0] == "identity"

    raw = yaml.safe_load(path.read_bytes())
    drifted = copy.deepcopy(raw)
    drifted["standard_scenarios"][1]["parameters"]["multiplier"] = 0.95
    with pytest.raises(ValidationError, match="default_demand_stress_levels"):
        FlowScenarioConfig(**drifted)
    widened = copy.deepcopy(raw)
    widened["coverage_guarantee"] = True
    with pytest.raises(ValidationError, match="cannot claim coverage"):
        FlowScenarioConfig(**widened)


def test_retrospective_evaluation_labels_are_declared_as_non_serving_context():
    result = evaluate_scenario(
        baseline_daily(),
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec("demand_multiplier", parameters={"multiplier": 1.1}),
    )
    declared = result.metadata["retrospective_evaluation_labels"]
    assert declared["serving_eligible"] is False
    assert "not scenario predictions" in declared["semantics"]
    present = set(result.daily_cells.columns) | set(result.entity_signals.columns)
    retrospective = set(declared["fields"]) & present
    assert {"phase", "y", "actual_exceeds_threshold"} <= retrospective
    assert result.metadata["serving_claim"] is False
    assert result.metadata["execution_mode"] == "EVALUATION"


def test_hierarchy_stays_exact_across_every_region_and_profile_after_a_transfer():
    daily = baseline_daily()
    result = evaluate_scenario(
        daily,
        anomalies(),
        pressure_config(),
        prioritization_config(),
        spec(
            "inflow_transfer",
            classification=ScenarioClassification.MECHANISTIC_ACCOUNTING_SCENARIO,
            scope=ScenarioScope(scope_type=ScopeType.PROFILE, profile_id="p1"),
            parameters={"source_hospital_id": "h1", "destination_hospital_id": "h3", "fraction": 0.4},
        ),
    )
    hierarchy = result.hierarchy_cells
    assert hierarchy_coherence(hierarchy)["within_tolerance"]
    assert set(hierarchy.loc[hierarchy["hierarchy_level"].eq("region"), "region_id"]) == {"r1", "r2"}
    assert set(hierarchy.loc[hierarchy["hierarchy_level"].eq("hospital"), "profile_id"]) == {"p1", "p2"}
    # The transfer crosses regions, so neither region sum is conserved but the national total is.
    national = hierarchy[hierarchy["hierarchy_level"].eq("national") & hierarchy["target"].eq("registrations")]
    np.testing.assert_allclose(
        national["scenario_central"].sum(), national["baseline_central"].sum(), atol=1e-9, rtol=0
    )
    regions = hierarchy[hierarchy["hierarchy_level"].eq("region") & hierarchy["target"].eq("registrations")]
    moved = regions["scenario_central"] - regions["baseline_central"]
    assert moved.abs().max() > 0
    assert result.validation["conservation"]["status"] == "PASS"
