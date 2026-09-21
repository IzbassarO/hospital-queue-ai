from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

import hqai_ml.flow_forecast.decision_alternatives as decision_alternatives_module
from hqai_ml.flow_forecast.config import FlowPressureConfig, SignalPrioritizationConfig
from hqai_ml.flow_forecast.decision_alternatives import (
    ACCEPTED_SOURCE_RUN_IDS,
    ALGORITHM,
    AbstentionCode,
    FullVerificationCache,
    InternalCandidate,
    VerificationCacheEntry,
    VerificationCacheKey,
    _candidate_for_receiver,
    _daily_support_class,
    _first_reason_code,
    _local_transformed,
    _state,
    assert_public_contract,
    derive_donor_minimum,
    derive_receiver_maximum,
    display_order,
    dominates,
    generate_decision_alternative_set,
    load_decision_alternatives_config,
    pareto_filter,
)
from hqai_ml.flow_forecast.pressure import SEVERITY_RANK, aggregate_pressure_signals, derive_daily_pressure_signals
from hqai_ml.flow_forecast.prioritization import _direct_supported, prepare_inbox
from hqai_ml.flow_forecast.scenario import ScenarioEvaluation, evaluate_scenario
from pipelines.decision_alternatives import (
    _acceptance_summary,
    _require_donor_daily_integrity,
    _require_nonempty_donors,
    _selected_donors,
    _verification_plan_estimate,
)

ROOT = Path(__file__).resolve().parents[2]


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


def config():
    return load_decision_alternatives_config(ROOT / "ml" / "configs" / "decision_alternatives.yaml")


def public_provenance(resolved_config=None) -> dict:
    resolved_config = resolved_config or config()
    return {
        "accepted_source_run_ids": ACCEPTED_SOURCE_RUN_IDS,
        "scenario_contract_version": resolved_config.scenario_contract_version,
        "scenario_scientific_identity": "a" * 64,
        "decision_config_identity_sha256": resolved_config.identity_sha256,
        "code_identity_sha256": "b" * 64,
        "execution_mode": "EVALUATION",
    }


def anomaly_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["forecast_origin", "series_id", "anomaly_status"])


def baseline_fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    origin = pd.Timestamp("2025-02-16")
    entities = [
        # hospital, region, profile, central, lower, upper, threshold, uncertainty, threshold support, forecast support
        ("h1", "r1", "p1", 10.0, 9.0, 11.0, 8.0, True, True, True),
        ("h2", "r1", "p1", 2.0, 1.0, 3.0, 10.0, True, True, True),
        ("h3", "r1", "p1", 7.0, 6.0, 8.0, 8.0, True, True, True),
        ("h4", "r1", "p1", 0.0, np.nan, np.nan, 20.0, False, True, False),
        ("h5", "r1", "p1", 1.0, 0.0, 2.0, np.nan, True, False, True),
        ("h6", "r2", "p1", 0.0, 0.0, 1.0, 20.0, True, True, True),
        ("h7", "r1", "p2", 0.0, 0.0, 1.0, 20.0, True, True, True),
    ]
    forecasts = []
    thresholds = []
    for target in ("registrations", "cohort_hospitalizations"):
        for hospital, region, profile, central, lower, upper, threshold, usable, supported, direct in entities:
            for horizon in range(1, 15):
                series_id = f"hp:{hospital}:{profile}"
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
                        "y": central,
                        "forecast_value": central,
                        "forecast_source": "direct_quantile_ml" if direct else "parent_scaled_direct_quantile_ml",
                        "hierarchy_status": "bottom_up_child_unchanged",
                        "support_status": "supported" if direct else "limited_history",
                        "fallback_status": "not_applicable" if direct else "regional_fallback",
                        "uncertainty_status": ("level_local_calibrated" if usable else "uncertainty_unavailable"),
                        "calibration_version": "cal-v1",
                        "calibration_status": "calibrated" if usable else "unavailable",
                        "level_local_interval_80_lower": lower,
                        "level_local_interval_80_upper": upper,
                        "hierarchy_alternative": "bottom_up_hospital",
                        "fallback_candidate": "current_region_profile_share",
                    }
                )
                thresholds.append(
                    {
                        "origin": origin,
                        "target": target,
                        "series_id": series_id,
                        "horizon": horizon,
                        "target_date": origin + pd.Timedelta(days=horizon),
                        "threshold_status": "supported" if supported else "unsupported",
                        "threshold_value": threshold,
                        "threshold_fallback_level": (
                            "hospital_date_class" if supported else "unsupported_insufficient_history"
                        ),
                        "threshold_semantics": "historical_flow_proxy_v1",
                    }
                )
    daily = derive_daily_pressure_signals(pd.DataFrame(forecasts), pd.DataFrame(thresholds), pressure_config())
    entity = aggregate_pressure_signals(daily, pressure_config())
    inbox, _, _, _ = prepare_inbox(entity, anomaly_frame(), prioritization_config())
    return daily, entity, inbox


def donor_receiver(
    daily: pd.DataFrame,
    receiver_id: str = "h2",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    registrations = daily[daily["target"].eq("registrations")]
    donor = registrations[registrations["hospital_id"].eq("h1")].sort_values("horizon").reset_index(drop=True)
    receiver = registrations[registrations["hospital_id"].eq(receiver_id)].sort_values("horizon").reset_index(drop=True)
    return donor, receiver


def donor_signal(inbox: pd.DataFrame) -> pd.Series:
    return inbox[inbox["hospital_id"].eq("h1")].iloc[0]


@pytest.mark.parametrize(
    ("reason_codes", "expected"),
    [
        (["A", "B"], "A"),
        (("A", "B"), "A"),
        (np.array(["A", "B"], dtype=object), "A"),
        ([], None),
        ((), None),
        (np.array([], dtype=object), None),
        (None, None),
        (pd.NA, None),
    ],
)
def test_first_reason_code_normalizes_sequence_and_missing_representations(reason_codes, expected):
    assert _first_reason_code(None, reason_codes) == expected


def test_first_reason_code_prefers_explicit_scalar_and_falls_back_from_missing_scalar():
    reasons = np.array(["ARRAY_FIRST", "ARRAY_SECOND"], dtype=object)
    assert _first_reason_code("EXPLICIT", reasons) == "EXPLICIT"
    assert _first_reason_code(np.nan, reasons) == "ARRAY_FIRST"
    assert _first_reason_code(pd.NA, reasons) == "ARRAY_FIRST"


def test_state_handles_real_parquet_numpy_reason_code_arrays_and_empty_arrays():
    daily, _, _ = baseline_fixture()
    donor, _ = donor_receiver(daily)
    donor = donor.drop(columns=["source_reason_code"], errors="ignore")
    donor["reason_codes"] = [np.array(["A", "B"], dtype=object) for _ in range(len(donor))]
    assert {cell["source_reason_code"] for cell in _state(donor, scenario=False)["cells"]} == {"A"}

    donor["reason_codes"] = [np.array([], dtype=object) for _ in range(len(donor))]
    assert {cell["source_reason_code"] for cell in _state(donor, scenario=False)["cells"]} == {None}

    donor["source_reason_code"] = pd.NA
    donor["reason_codes"] = [np.array(["FALLBACK"], dtype=object) for _ in range(len(donor))]
    assert {cell["source_reason_code"] for cell in _state(donor, scenario=False)["cells"]} == {"FALLBACK"}


def test_config_precommits_real_data_acceptance_values_and_rejects_safety_drift(tmp_path: Path):
    resolved = config()
    assert resolved.donor_cohort.top_n_primary_donors == 20
    assert resolved.donor_cohort.top_n_fallback_donors == 20
    assert resolved.transfer_budget_ladder == [0.05, 0.10, 0.25, 1.0]
    assert resolved.receiver_policy.same_profile and resolved.receiver_policy.same_region
    assert resolved.algorithm == ALGORITHM
    raw = yaml.safe_load((ROOT / "ml" / "configs" / "decision_alternatives.yaml").read_text())
    raw["capacity_checked"] = True
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValidationError):
        load_decision_alternatives_config(path)


def test_phi_zero_is_bit_identical_for_pair_and_conserves_every_horizon():
    daily, _, _ = baseline_fixture()
    donor, receiver = donor_receiver(daily)
    transformed = _local_transformed(donor, receiver, 0.0)
    for hospital_id, baseline in (("h1", donor), ("h2", receiver)):
        scenario = transformed[transformed["hospital_id"].eq(hospital_id)].sort_values("horizon")
        assert np.array_equal(scenario["scenario_central"].to_numpy(), baseline["forecast_value"].to_numpy())
        assert np.array_equal(
            scenario["scenario_sensitivity_lower"].to_numpy(), baseline["uncertainty_lower"].to_numpy()
        )
        assert np.array_equal(
            scenario["scenario_sensitivity_upper"].to_numpy(), baseline["uncertainty_upper"].to_numpy()
        )
        assert scenario["severity"].tolist() == baseline["severity"].tolist()


def test_algebraic_minimum_binding_tie_zero_threshold_and_float64_upward_certification():
    daily, _, _ = baseline_fixture()
    donor, _ = donor_receiver(daily)
    minimum = derive_donor_minimum(donor, 8)
    assert minimum.value == pytest.approx(0.2)
    assert minimum.binding_horizon == 1
    assert minimum.binding_horizons == tuple(range(1, 15))

    zero = donor.copy()
    zero["threshold_value"] = 0.0
    zero_minimum = derive_donor_minimum(zero, 8)
    assert zero_minimum.value == 1.0
    assert zero_minimum.zero_threshold_binding_present

    rounding = donor.copy()
    rounding["forecast_value"] = 0.3
    rounding["threshold_value"] = 0.1
    rounded_float = float(1.0 - 0.1 / 0.3)
    assert 0.3 - rounded_float * 0.3 <= 0.1  # rounded-product-only check appears to pass
    certified = derive_donor_minimum(rounding, 1)
    assert certified.certify_up_steps == 1
    assert certified.value == math.nextafter(float(certified.algebraic), math.inf)
    with pytest.raises(ValueError, match=AbstentionCode.PHI_CERTIFICATION_FAILED.value):
        derive_donor_minimum(rounding, 0)


@pytest.mark.parametrize(
    ("central", "lower", "upper", "threshold", "expected_severity", "expected_bound"),
    [
        (4.0, 3.0, 5.0, 6.0, "NORMAL", 0.1),
        (4.0, 3.0, 7.0, 6.0, "WATCH", 0.2),
        (7.0, 3.0, 8.0, 6.0, "ELEVATED", 0.3),
        (7.0, 7.0, 8.0, 6.0, "HIGH", 1.0),
    ],
)
def test_receiver_phi_max_for_each_baseline_severity(
    central: float,
    lower: float,
    upper: float,
    threshold: float,
    expected_severity: str,
    expected_bound: float,
):
    daily, _, _ = baseline_fixture()
    donor, receiver = donor_receiver(daily)
    donor["forecast_value"] = 10.0
    receiver["forecast_value"] = central
    receiver["uncertainty_lower"] = lower
    receiver["uncertainty_upper"] = upper
    receiver["threshold_value"] = threshold
    receiver["severity"] = expected_severity
    maximum = derive_receiver_maximum(donor, receiver, 8)
    assert maximum.value == pytest.approx(expected_bound)


def test_zero_threshold_receiver_raw_severity_and_missing_range_masking():
    daily, _, _ = baseline_fixture()
    donor, receiver = donor_receiver(daily)
    receiver[["forecast_value", "threshold_value", "uncertainty_lower", "uncertainty_upper"]] = 0.0
    receiver["severity"] = "NORMAL"
    maximum = derive_receiver_maximum(donor, receiver, 8)
    assert maximum.value == 0.0

    _, range_limited = donor_receiver(daily, "h4")
    donor_minimum = derive_donor_minimum(donor, 8)
    candidate, code = _candidate_for_receiver(
        donor,
        range_limited,
        donor_minimum,
        "DIRECT_SUPPORTED",
        "FALLBACK_LIMITED",
        1.0,
        None,
        8,
    )
    assert code is None and candidate is not None
    assert candidate.forecast_support_tier == "FALLBACK_LIMITED"
    assert candidate.receiver_range_evidence == "RANGE_LIMITED"
    assert candidate.fast["receiver_range_masking_present"]
    assert candidate.fast["sensitivity_range_result"] == "RANGE_EVIDENCE_INCOMPLETE"


def test_policy_budget_is_not_receiver_bound_and_conservation_is_exact_enough():
    daily, _, _ = baseline_fixture()
    donor, receiver = donor_receiver(daily)
    donor_minimum = derive_donor_minimum(donor, 8)
    candidate, code = _candidate_for_receiver(
        donor,
        receiver,
        donor_minimum,
        "DIRECT_SUPPORTED",
        "DIRECT_SUPPORTED",
        0.1,
        None,
        8,
    )
    assert candidate is None and code == AbstentionCode.TRANSFER_BUDGET_INSUFFICIENT
    candidate, code = _candidate_for_receiver(
        donor,
        receiver,
        donor_minimum,
        "DIRECT_SUPPORTED",
        "DIRECT_SUPPORTED",
        1.0,
        None,
        8,
    )
    assert code is None and candidate is not None
    assert candidate.fast["pair_conservation_max_absolute_error"] <= 1e-9
    assert candidate.fast["receiver_no_worse_constraint_satisfied"]
    assert candidate.fast["donor_severity_never_worsened"]


def test_donor_and_receiver_severity_are_monotone_and_receiver_feasible_set_is_closed_interval():
    daily, _, _ = baseline_fixture()
    donor, receiver = donor_receiver(daily)
    donor_ranks = []
    receiver_ranks = []
    for phi in (0.0, 0.1, 0.2, 0.5, 0.7, math.nextafter(0.7, math.inf), 1.0):
        transformed = _local_transformed(donor, receiver, phi)
        donor_ranks.append(transformed[transformed["hospital_id"].eq("h1")]["severity"].map(SEVERITY_RANK).to_numpy())
        receiver_ranks.append(
            transformed[transformed["hospital_id"].eq("h2")]["severity"].map(SEVERITY_RANK).to_numpy()
        )
        assert (transformed[transformed["hospital_id"].eq("h1")]["scenario_central"] >= 0).all()
    assert all(np.all(left >= right) for left, right in zip(donor_ranks[:-1], donor_ranks[1:], strict=True))
    assert all(np.all(left <= right) for left, right in zip(receiver_ranks[:-1], receiver_ranks[1:], strict=True))
    maximum = derive_receiver_maximum(donor, receiver, 8)
    baseline_rank = receiver["severity"].map(SEVERITY_RANK).to_numpy()
    at_bound = _local_transformed(donor, receiver, maximum.value)
    above_bound = _local_transformed(donor, receiver, maximum.value + 1e-12)
    assert np.all(at_bound[at_bound["hospital_id"].eq("h2")]["severity"].map(SEVERITY_RANK).to_numpy() <= baseline_rank)
    assert np.any(
        above_bound[above_bound["hospital_id"].eq("h2")]["severity"].map(SEVERITY_RANK).to_numpy() > baseline_rank
    )


def candidate(receiver_id: str, severity: str, headroom: float, tier: str = "DIRECT_SUPPORTED") -> InternalCandidate:
    return InternalCandidate(
        receiver_id=receiver_id,
        receiver_region_id="r1",
        receiver_series_id=f"hp:{receiver_id}:p1",
        transfer_fraction=0.2,
        certify_up_steps=0,
        receiver_phi_max=1.0,
        receiver_binding_cell=None,
        donor_support_class="DIRECT_SUPPORTED",
        receiver_support_class=tier,
        forecast_support_tier=tier,
        receiver_range_evidence="COMPLETE",
        fast={
            "transferred_expected_registrations_total": 28.0,
            "receiver_worst_severity_after": severity,
            "receiver_min_central_headroom": headroom,
        },
    )


def test_pareto_dominance_is_stratum_local_and_display_order_is_deterministic():
    a = candidate("a", "NORMAL", 5.0)
    b = candidate("b", "WATCH", 4.0)
    fallback = candidate("c", "WATCH", 1.0, "FALLBACK_LIMITED")
    assert dominates(a, b)
    assert not dominates(a, fallback)
    assert pareto_filter([a, b, fallback]) == [a, fallback]
    assert sorted([fallback, a], key=display_order) == [a, fallback]
    assert not dominates(a, a)


def test_full_engine_verification_publishes_only_verified_alternatives_and_is_deterministic():
    daily, entity, inbox = baseline_fixture()
    kwargs = {
        "baseline_daily": daily,
        "baseline_entity": entity,
        "donor_signal": donor_signal(inbox),
        "anomalies": anomaly_frame(),
        "pressure_config": pressure_config(),
        "prioritization_config": prioritization_config(),
        "config": config(),
        "max_transfer_fraction": 1.0,
        "provenance": public_provenance(),
    }
    first = generate_decision_alternative_set(**kwargs)
    second = generate_decision_alternative_set(**kwargs)
    assert first == second
    assert first["alternatives"]
    assert all(item["verification_state"] == "VERIFIED_FULL_ENGINE" for item in first["alternatives"])
    assert all(item["verification_only_fields"] is not None for item in first["alternatives"])
    assert not first["verification_failures"]
    assert first["scientific_output_sha256"] == second["scientific_output_sha256"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    primary = [
        item
        for item in first["alternatives"]
        if item["forecast_support_tier"] == "DIRECT_SUPPORTED" and item["receiver_range_evidence"] == "COMPLETE"
    ]
    assert primary
    assert primary[0]["transfer_fraction_decimal"] == format(primary[0]["transfer_fraction"], ".17g")
    assert float.fromhex(primary[0]["phi_hex"]) == primary[0]["transfer_fraction"]
    assert primary[0]["feasibility_status"] == "NOT_PHYSICAL_CAPACITY_VALIDATED"
    assert primary[0]["capacity_checked"] is False
    assert primary[0]["causal_effect_claimed"] is False
    assert primary[0]["range_recalibrated"] is False
    assert primary[0]["coverage_guarantee"] is False
    assert primary[0]["human_review_required"] is True
    assert primary[0]["donor"]["profile_id"] == primary[0]["receiver"]["profile_id"]
    assert primary[0]["donor_binding_horizons"] == list(range(1, 15))
    assert "patient" not in json.dumps(first).lower()
    assert all(isinstance(item["moved"], float) for item in primary[0]["transferred_by_horizon"])


def test_full_verification_preserves_secondary_target_thresholds_provenance_and_parent_sums():
    daily, entity, inbox = baseline_fixture()
    calls = 0

    def checking_evaluator(*args, **kwargs):
        nonlocal calls
        calls += 1
        baseline = args[0]
        result = evaluate_scenario(*args, **kwargs)
        secondary = result.daily_cells["target"].eq("cohort_hospitalizations")
        assert np.array_equal(
            result.daily_cells.loc[secondary, "baseline_central"].to_numpy(),
            result.daily_cells.loc[secondary, "scenario_central"].to_numpy(),
        )
        keys = ["phase", "origin", "target", "series_id", "horizon"]
        unchanged = [
            "threshold_value",
            "threshold_status",
            "threshold_fallback_level",
            "threshold_semantics",
            "support_status",
            "fallback_status",
            "forecast_source",
        ]
        left = baseline[keys + unchanged].sort_values(keys).reset_index(drop=True)
        right = result.daily_cells[keys + unchanged].sort_values(keys).reset_index(drop=True)
        pd.testing.assert_frame_equal(left, right)
        left_calibration = baseline[keys + ["calibration_version"]].sort_values(keys).reset_index(drop=True)
        right_calibration = (
            result.daily_cells[keys + ["baseline_calibration_version"]].sort_values(keys).reset_index(drop=True)
        )
        assert left_calibration["calibration_version"].equals(right_calibration["baseline_calibration_version"])
        parents = result.hierarchy_cells[result.hierarchy_cells["hierarchy_level"].isin(["region", "national"])]
        assert np.allclose(
            parents["baseline_central"],
            parents["scenario_central"],
            atol=1e-9,
            rtol=0,
        )
        assert result.validation["hierarchy_coherence"]["region_max_absolute_error"] == 0
        assert result.validation["hierarchy_coherence"]["national_max_absolute_error"] == 0
        return result

    result = generate_decision_alternative_set(
        baseline_daily=daily,
        baseline_entity=entity,
        donor_signal=donor_signal(inbox),
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=config(),
        max_transfer_fraction=1.0,
        provenance=public_provenance(),
        full_evaluator=checking_evaluator,
    )
    assert calls
    assert result["alternatives"]


def test_shortlist_bound_is_per_stratum_and_drops_are_separate_non_alternatives():
    daily, _, _ = baseline_fixture()
    clone = daily[daily["hospital_id"].eq("h2")].copy()
    clone["hospital_id"] = "h8"
    clone["org_code"] = "h8"
    clone["series_id"] = "hp:h8:p1"
    daily = pd.concat([daily, clone], ignore_index=True)
    entity = aggregate_pressure_signals(daily, pressure_config())
    inbox, _, _, _ = prepare_inbox(entity, anomaly_frame(), prioritization_config())
    cfg = config().model_copy(update={"shortlist_max_alternatives": 1})
    result = generate_decision_alternative_set(
        baseline_daily=daily,
        baseline_entity=entity,
        donor_signal=donor_signal(inbox),
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=cfg,
        max_transfer_fraction=1.0,
        provenance=public_provenance(),
    )
    assert result["alternatives_dropped_by_shortlist_bound"]
    assert result["alternatives_pareto_surviving"] > result["alternatives_shortlisted"]
    assert all("verification_state" not in item for item in result["alternatives_dropped_by_shortlist_bound"])


def test_fast_or_failed_candidates_never_enter_public_alternatives():
    daily, entity, inbox = baseline_fixture()

    def disagree(*args, **kwargs):
        result = __import__("hqai_ml.flow_forecast.scenario", fromlist=["evaluate_scenario"]).evaluate_scenario(
            *args, **kwargs
        )
        receiver = result.spec.parameters["destination_hospital_id"]
        index = result.daily_cells[
            result.daily_cells["hospital_id"].eq(receiver) & result.daily_cells["target"].eq("registrations")
        ].index[0]
        result.daily_cells.loc[index, "scenario_central"] += 1.0
        return result

    result = generate_decision_alternative_set(
        baseline_daily=daily,
        baseline_entity=entity,
        donor_signal=donor_signal(inbox),
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=config(),
        max_transfer_fraction=1.0,
        provenance=public_provenance(),
        full_evaluator=disagree,
    )
    assert not result["alternatives"]
    assert result["verification_failures"]
    assert AbstentionCode.FULL_VERIFICATION_FAILED.value in result["abstention_status"]["codes"]
    assert "FAST_EVALUATOR_ONLY" not in json.dumps(result)


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda signal, daily: signal.__setitem__("threshold_status", "unsupported"), "UNSUPPORTED_SIGNAL"),
        (lambda signal, daily: signal.__setitem__("source_severity", "WATCH"), "UNSUPPORTED_SIGNAL"),
        (
            lambda signal, daily: signal.__setitem__("operational_priority_status", "zero_baseline_low_volume"),
            "DONOR_NOT_MATERIALLY_ELIGIBLE",
        ),
    ],
)
def test_donor_abstention(mutator, expected: str):
    daily, entity, inbox = baseline_fixture()
    signal = donor_signal(inbox).copy()
    mutator(signal, daily)
    result = generate_decision_alternative_set(
        baseline_daily=daily,
        baseline_entity=entity,
        donor_signal=signal,
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=config(),
        max_transfer_fraction=1.0,
        provenance=public_provenance(),
    )
    assert not result["alternatives"]
    assert expected in result["abstention_status"]["codes"]


@pytest.mark.parametrize("source_severity", ["WATCH", "HIGH"])
def test_inconsistent_watch_or_range_driven_high_without_central_exceedance_abstains_not_central_driven(
    source_severity: str,
):
    daily, entity, inbox = baseline_fixture()
    signal = donor_signal(inbox).copy()
    donor_mask = daily["hospital_id"].eq("h1") & daily["target"].eq("registrations")
    daily.loc[donor_mask, "forecast_value"] = 8.0
    daily.loc[donor_mask, "severity"] = "HIGH"
    signal["source_severity"] = source_severity
    result = generate_decision_alternative_set(
        baseline_daily=daily,
        baseline_entity=entity,
        donor_signal=signal,
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=config(),
        max_transfer_fraction=1.0,
        provenance=public_provenance(),
    )
    assert result["abstention_status"]["codes"] == ["DONOR_NOT_CENTRAL_DRIVEN"]


def test_receiver_unsupported_alignment_and_budget_abstentions_are_explicit():
    daily, entity, inbox = baseline_fixture()
    cfg = config()
    cfg = cfg.model_copy(
        update={"receiver_policy": cfg.receiver_policy.model_copy(update={"eligible_receiver_ids": ["h3"]})}
    )
    budget = generate_decision_alternative_set(
        baseline_daily=daily,
        baseline_entity=entity,
        donor_signal=donor_signal(inbox),
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=cfg,
        max_transfer_fraction=0.1,
        provenance=public_provenance(cfg),
    )
    assert "RECEIVER_BLOCKED" in budget["abstention_status"]["codes"]

    cfg = config().model_copy(
        update={"receiver_policy": config().receiver_policy.model_copy(update={"eligible_receiver_ids": ["h5"]})}
    )
    unsupported = generate_decision_alternative_set(
        baseline_daily=daily,
        baseline_entity=entity,
        donor_signal=donor_signal(inbox),
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=cfg,
        max_transfer_fraction=1.0,
        provenance=public_provenance(cfg),
    )
    assert "RECEIVER_UNSUPPORTED_EVIDENCE" in json.dumps(unsupported["abstention_status"])

    missing = daily[~(daily["hospital_id"].eq("h2") & daily["horizon"].eq(14))].copy()
    cfg = config().model_copy(
        update={"receiver_policy": config().receiver_policy.model_copy(update={"eligible_receiver_ids": ["h2"]})}
    )
    alignment = generate_decision_alternative_set(
        baseline_daily=missing,
        baseline_entity=entity,
        donor_signal=donor_signal(inbox),
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=cfg,
        max_transfer_fraction=1.0,
        provenance=public_provenance(cfg),
    )
    assert "RECEIVER_ALIGNMENT_INCOMPLETE" in json.dumps(alignment["abstention_status"])


def test_public_contract_rejects_forbidden_fields_and_unverified_members():
    with pytest.raises(ValueError, match="forbidden public field"):
        assert_public_contract({"alternatives": [], "recommended_action": None, "provenance": public_provenance()})
    with pytest.raises(ValueError, match="VERIFIED_FULL_ENGINE"):
        assert_public_contract(
            {
                "alternatives": [{"verification_state": "FAST_EVALUATOR_ONLY"}],
                "provenance": public_provenance(),
            }
        )


def test_source_files_for_accepted_science_are_unchanged_by_implementation():
    protected = {
        "ml/hqai_ml/flow_forecast/scenario.py": "17ba920611bfdb3c0ca9b825baed2343602edf85f9d1c7a32df04ff6de2c4f18",
        "ml/hqai_ml/flow_forecast/pressure.py": "5586da0dc89a37a997ac0de5d8ed992a27b386d1851a33e11c56751894a1fe33",
        "ml/hqai_ml/flow_forecast/prioritization.py": (
            "2c7933ec7953d63d1da953cd5d9db589dfb3448737eb60642f94931cdb916566"
        ),
    }
    for path, expected_sha256 in protected.items():
        actual_sha256 = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        assert actual_sha256 == expected_sha256, (
            f"protected science file drifted: {path}; expected SHA-256 {expected_sha256}, got {actual_sha256}"
        )


def test_no_solver_or_hidden_score_dependency_or_contract_key():
    module = (ROOT / "ml" / "hqai_ml" / "flow_forecast" / "decision_alternatives.py").read_text()
    forbidden_imports = ("import ortools", "import pulp", "import scipy.optimize", "import cvxpy", "openai")
    assert not any(item in module.lower() for item in forbidden_imports)
    assert "weighted_score" not in module
    assert "composite_score" not in module


def test_full_verification_cache_reuses_successes_across_budget_rungs_and_is_byte_stable():
    daily, entity, inbox = baseline_fixture()
    cfg = config()
    cache = FullVerificationCache()
    calls = 0
    verification_daily_ids = []

    def counting_evaluator(*args, **kwargs):
        nonlocal calls
        calls += 1
        verification_daily_ids.append(id(args[0]))
        return evaluate_scenario(*args, **kwargs)

    common = {
        "baseline_daily": daily,
        "baseline_entity": entity,
        "donor_signal": donor_signal(inbox),
        "anomalies": anomaly_frame(),
        "pressure_config": pressure_config(),
        "prioritization_config": prioritization_config(),
        "config": cfg,
        "provenance": public_provenance(cfg),
        "full_evaluator": counting_evaluator,
        "verification_cache": cache,
    }
    lower = generate_decision_alternative_set(max_transfer_fraction=0.25, **common)
    calls_after_lower = calls
    upper = generate_decision_alternative_set(max_transfer_fraction=1.0, **common)
    repeated_lower = generate_decision_alternative_set(max_transfer_fraction=0.25, **common)

    assert lower["alternatives"] and upper["alternatives"]
    assert calls_after_lower > 0
    assert calls == calls_after_lower
    assert cache.evaluation_count == calls_after_lower
    assert cache.reuse_count >= len(upper["alternatives"]) + len(repeated_lower["alternatives"])
    assert len(set(verification_daily_ids)) == 1
    assert json.dumps(lower, sort_keys=True) == json.dumps(repeated_lower, sort_keys=True)

    def contains_large_engine_payload(value) -> bool:
        if isinstance(value, (pd.DataFrame, ScenarioEvaluation)):
            return True
        if is_dataclass(value):
            return any(contains_large_engine_payload(getattr(value, field.name)) for field in fields(value))
        if isinstance(value, dict):
            return any(contains_large_engine_payload(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(contains_large_engine_payload(item) for item in value)
        return False

    assert cache.entries
    assert all(isinstance(entry, VerificationCacheEntry) for entry in cache.entries)
    assert not contains_large_engine_payload(cache.entries)
    cached_by_output = {entry.scientific_output_sha256: entry for entry in cache.entries if entry.succeeded}
    for alternative in lower["alternatives"]:
        entry = cached_by_output[alternative["provenance"]["scenario_scientific_output_sha256"]]
        assert alternative["provenance"]["verification_scenario"] == entry.scenario_spec_scientific_payload()
        assert alternative["verification_only_fields"] == entry.verification_only_fields()


def test_full_verification_cache_reuses_failures_without_reinvoking_engine():
    daily, entity, inbox = baseline_fixture()
    cache = FullVerificationCache()
    calls = 0

    def failing_evaluator(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("deterministic full-engine failure")

    kwargs = {
        "baseline_daily": daily,
        "baseline_entity": entity,
        "donor_signal": donor_signal(inbox),
        "anomalies": anomaly_frame(),
        "pressure_config": pressure_config(),
        "prioritization_config": prioritization_config(),
        "config": config(),
        "max_transfer_fraction": 1.0,
        "provenance": public_provenance(),
        "full_evaluator": failing_evaluator,
        "verification_cache": cache,
    }
    first = generate_decision_alternative_set(**kwargs)
    first_calls = calls
    second = generate_decision_alternative_set(**kwargs)

    assert first_calls > 0 and calls == first_calls
    assert cache.reuse_count == first_calls
    assert first == second
    assert not first["alternatives"]
    assert first["verification_failures"]
    assert all(not entry.succeeded for entry in cache.entries)
    assert all(entry.failure_code == AbstentionCode.FULL_VERIFICATION_FAILED.value for entry in cache.entries)
    assert all(entry.scenario_spec_scientific_payload_json is None for entry in cache.entries)


def test_verification_cache_key_separates_receiver_phi_origin_and_phase():
    cache = FullVerificationCache()
    base = VerificationCacheKey(
        origin="2025-02-16",
        phase="validation",
        target="registrations",
        region_id="r1",
        profile_id="p1",
        donor_hospital_id="h1",
        donor_series_id="hp:h1:p1",
        receiver_hospital_id="h2",
        receiver_series_id="hp:h2:p1",
        phi_hex=(0.2).hex(),
        scenario_contract_version="forecast-stress-test-v1",
        hierarchy_run_id=ACCEPTED_SOURCE_RUN_IDS["hierarchy"],
        pressure_run_id=ACCEPTED_SOURCE_RUN_IDS["pressure"],
        prioritization_run_id=ACCEPTED_SOURCE_RUN_IDS["prioritization"],
        scenario_run_id=ACCEPTED_SOURCE_RUN_IDS["scenario"],
        scenario_scientific_identity="a" * 64,
        decision_config_identity_sha256=config().identity_sha256,
        code_identity_sha256="b" * 64,
    )
    keys = [
        base,
        replace(base, receiver_hospital_id="h3", receiver_series_id="hp:h3:p1"),
        replace(base, phi_hex=(0.25).hex()),
        replace(base, origin="2025-02-23"),
        replace(base, phase="final_test"),
    ]
    calls = 0

    def evaluate():
        nonlocal calls
        calls += 1
        return object()

    for key in keys:
        cache.verify(
            key,
            "fast-fingerprint",
            evaluate,
            lambda result: None,
            lambda result: ({}, "c" * 64, {}),
        )
    for key in keys:
        cache.verify(
            key,
            "fast-fingerprint",
            evaluate,
            lambda result: None,
            lambda result: ({}, "c" * 64, {}),
        )
    assert calls == len(keys)
    assert cache.unique_scenarios == len(keys)
    assert cache.reuse_count == len(keys)

    with pytest.raises(ValueError, match="fast-payload fingerprint mismatch"):
        cache.verify(
            base,
            "different-fast-fingerprint",
            evaluate,
            lambda result: None,
            lambda result: ({}, "c" * 64, {}),
        )


def test_final_float64_certification_retries_upward_and_abstains_on_guard_exhaustion(monkeypatch):
    daily, _, _ = baseline_fixture()
    donor, receiver = donor_receiver(daily)
    donor_minimum = derive_donor_minimum(donor, 8)
    calls = 0

    def succeeds_after_one_step(*args, **kwargs):
        nonlocal calls
        calls += 1
        return (calls > 1, False)

    monkeypatch.setattr(decision_alternatives_module, "_final_certification", succeeds_after_one_step)
    candidate, code = _candidate_for_receiver(
        donor,
        receiver,
        donor_minimum,
        "DIRECT_SUPPORTED",
        "DIRECT_SUPPORTED",
        1.0,
        None,
        donor_minimum.certify_up_steps + 1,
    )
    assert code is None and candidate is not None
    assert calls == 2
    assert candidate.certify_up_steps == donor_minimum.certify_up_steps + 1

    monkeypatch.setattr(decision_alternatives_module, "_final_certification", lambda *args, **kwargs: (False, False))
    failed, code = _candidate_for_receiver(
        donor,
        receiver,
        donor_minimum,
        "DIRECT_SUPPORTED",
        "DIRECT_SUPPORTED",
        1.0,
        None,
        donor_minimum.certify_up_steps,
    )
    assert failed is None and code == AbstentionCode.PHI_CERTIFICATION_FAILED


def test_receiver_negative_lower_value_and_zero_threshold_severity_cases():
    daily, _, _ = baseline_fixture()
    donor, receiver = donor_receiver(daily)
    receiver["forecast_value"] = 7.0
    receiver["uncertainty_lower"] = -2.0
    receiver["uncertainty_upper"] = 8.0
    receiver["threshold_value"] = 6.0
    receiver["severity"] = "ELEVATED"
    maximum = derive_receiver_maximum(donor, receiver, 8)
    assert maximum.value == pytest.approx(0.8)
    assert maximum.binding_cell["predicate"] == "SENSITIVITY_LOWER"

    receiver["forecast_value"] = 1.0
    receiver["threshold_value"] = 0.0
    receiver["uncertainty_lower"] = 0.0
    receiver["uncertainty_upper"] = 2.0
    receiver["severity"] = "ELEVATED"
    assert derive_receiver_maximum(donor, receiver, 8).value == 0.0

    receiver["uncertainty_lower"] = 1.0
    receiver["severity"] = "HIGH"
    assert derive_receiver_maximum(donor, receiver, 8).value == 1.0

    receiver[["uncertainty_lower", "uncertainty_upper"]] = np.nan
    receiver["uncertainty_status"] = "uncertainty_unavailable"
    receiver["severity"] = "ELEVATED"
    assert derive_receiver_maximum(donor, receiver, 8).value == 1.0


def test_direct_supported_receiver_can_independently_have_range_limited_evidence():
    daily, _, _ = baseline_fixture()
    mask = daily["hospital_id"].eq("h4")
    daily.loc[mask, "support_status"] = "supported"
    daily.loc[mask, "fallback_status"] = "not_applicable"
    daily.loc[mask, "forecast_source"] = "direct_quantile_ml"
    entity = aggregate_pressure_signals(daily, pressure_config())
    inbox, _, _, _ = prepare_inbox(entity, anomaly_frame(), prioritization_config())
    result = generate_decision_alternative_set(
        baseline_daily=daily,
        baseline_entity=entity,
        donor_signal=donor_signal(inbox),
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=config(),
        max_transfer_fraction=1.0,
        provenance=public_provenance(),
    )
    h4 = next(item for item in result["alternatives"] if item["receiver"]["hospital_id"] == "h4")
    assert h4["forecast_support_tier"] == "DIRECT_SUPPORTED"
    assert h4["receiver_range_evidence"] == "RANGE_LIMITED"


def test_decision_support_class_matches_accepted_prioritization_rule():
    frame = pd.DataFrame(
        [
            {"support_status": "supported", "fallback_status": "not_applicable", "forecast_source": "direct"},
            {"support_status": "limited_history", "fallback_status": "not_applicable", "forecast_source": "direct"},
            {"support_status": "supported", "fallback_status": "regional_fallback", "forecast_source": "direct"},
            {
                "support_status": "supported",
                "fallback_status": "not_applicable",
                "forecast_source": "parent_scaled_fallback",
            },
        ]
    )
    accepted = _direct_supported(frame).tolist()
    decision = [_daily_support_class(row) == "DIRECT_SUPPORTED" for _, row in frame.iterrows()]
    assert decision == accepted


@pytest.mark.parametrize(
    "missing_field",
    ["scenario_contract_version", "decision_config_identity_sha256", "code_identity_sha256"],
)
def test_public_provenance_rejects_missing_required_identity_fields(missing_field: str):
    provenance = public_provenance()
    provenance.pop(missing_field)
    with pytest.raises(ValueError, match="provenance is missing fields"):
        assert_public_contract({"alternatives": [], "provenance": provenance})


def test_generator_rejects_changed_config_identity_and_public_provenance_has_no_fake_timestamp():
    daily, entity, inbox = baseline_fixture()
    changed = public_provenance()
    changed["decision_config_identity_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="different decision configuration identity"):
        generate_decision_alternative_set(
            baseline_daily=daily,
            baseline_entity=entity,
            donor_signal=donor_signal(inbox),
            anomalies=anomaly_frame(),
            pressure_config=pressure_config(),
            prioritization_config=prioritization_config(),
            config=config(),
            max_transfer_fraction=1.0,
            provenance=changed,
        )

    result = generate_decision_alternative_set(
        baseline_daily=daily,
        baseline_entity=entity,
        donor_signal=donor_signal(inbox),
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=config(),
        max_transfer_fraction=1.0,
        provenance=public_provenance(),
    )
    serialized = json.dumps(result, sort_keys=True)
    assert "created_at" not in serialized
    assert "2000-01-01" not in serialized
    assert result["provenance"]["accepted_source_run_ids"] == ACCEPTED_SOURCE_RUN_IDS


def test_config_rejects_any_unaccepted_source_run(tmp_path: Path):
    raw = yaml.safe_load((ROOT / "ml" / "configs" / "decision_alternatives.yaml").read_text())
    raw["source_scenario_run"] = "flow-scenario-unaccepted"
    path = tmp_path / "unaccepted-source.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ValidationError, match="accepted 6B.4 chain"):
        load_decision_alternatives_config(path)


def test_plan_estimate_is_read_only_and_reports_dedup_savings():
    daily, _, inbox = baseline_fixture()
    cfg = config()
    donors = donor_signal(inbox).to_frame().T
    estimate = _verification_plan_estimate(donors, daily, cfg)
    assert estimate["donor_count"] == 1
    assert estimate["receiver_candidate_count"] == 4  # h6 is same-profile but outside donor region r1
    assert estimate["fast_candidate_count"] is None
    assert estimate["full_scenario_evaluation_executed"] is False
    assert estimate["count_semantics"]["receiver_candidate_count"].startswith("EXACT_SAME_REGION")
    assert estimate["count_semantics"]["expected_unique_full_verification_count"] == "UPPER_BOUND"
    assert estimate["naive_pre_dedup_verification_count"] >= estimate["expected_unique_full_verification_count"]
    assert estimate["duplicate_verification_savings_estimate"] >= 0


def test_primary_and_fallback_donor_cohort_limits_are_independent():
    cfg = config()
    cfg = cfg.model_copy(
        update={
            "donor_cohort": cfg.donor_cohort.model_copy(update={"top_n_primary_donors": 2, "top_n_fallback_donors": 1})
        }
    )
    origin = pd.Timestamp(cfg.donor_cohort.origins[0])
    rows = []
    for support, count in (("direct_supported", 4), ("fallback_or_limited_history", 3)):
        for index in range(count):
            rows.append(
                {
                    "origin": origin,
                    "phase": "validation",
                    "target": "registrations",
                    "operational_priority_status": "primary_inbox_eligible",
                    "source_severity": "HIGH",
                    "priority_support_class": support,
                    "inbox_rank": index + 1,
                    "region_id": "r1",
                    "hospital_id": f"{support}-{index}",
                    "profile_id": "p1",
                }
            )
    selected = _selected_donors(pd.DataFrame(rows), cfg)
    assert selected["priority_support_class"].value_counts().to_dict() == {
        "direct_supported": 2,
        "fallback_or_limited_history": 1,
    }


def test_zero_selected_donor_guard_is_explicit():
    with pytest.raises(ValueError, match="ZERO_SELECTED_DONOR_UNITS"):
        _require_nonempty_donors(pd.DataFrame())


def test_selected_donor_cohort_fails_when_no_unit_joins_expected_daily_rows():
    daily, _, inbox = baseline_fixture()
    donors = donor_signal(inbox).to_frame().T
    _require_donor_daily_integrity(donors, daily)
    mismatched = daily.assign(origin=pd.Timestamp("1999-01-01"))
    with pytest.raises(ValueError, match="DONOR_DAILY_INPUT_JOIN_FAILED"):
        _require_donor_daily_integrity(donors, mismatched)


def test_acceptance_summary_uses_units_not_rejected_receiver_records_and_stays_pending():
    daily, entity, inbox = baseline_fixture()
    cfg = config()
    cache = FullVerificationCache()
    common = {
        "baseline_daily": daily,
        "baseline_entity": entity,
        "donor_signal": donor_signal(inbox),
        "anomalies": anomaly_frame(),
        "pressure_config": pressure_config(),
        "prioritization_config": prioritization_config(),
        "config": cfg,
        "provenance": public_provenance(cfg),
        "verification_cache": cache,
    }
    abstained = generate_decision_alternative_set(max_transfer_fraction=0.10, **common)
    published = generate_decision_alternative_set(max_transfer_fraction=0.25, **common)
    summary = _acceptance_summary(
        [abstained, published],
        cfg,
        unique_full_verifications=cache.evaluation_count,
        verification_cache_reuses=cache.reuse_count,
        runtime_seconds=1.25,
        peak_memory=64.0,
    )
    assert summary["acceptance_status"] == "EVIDENCE_GENERATED_REVIEW_PENDING"
    assert summary["real_data_acceptance_claimed"] is False
    assert summary["by_policy_budget"]["0.10"]["units_evaluated"] == 1
    assert summary["by_policy_budget"]["0.10"]["at_least_one_alternative_rate"] == 0.0
    assert summary["by_policy_budget"]["0.25"]["units_with_at_least_one_published_alternative"] == 1
    assert summary["by_policy_budget"]["0.25"]["at_least_one_alternative_rate"] == 1.0
    assert summary["by_policy_budget"]["0.25"]["unit_level_abstention_counts_by_reason"] == {}
    assert summary["verification_cache"]["unique_full_verifications"] == cache.evaluation_count
    assert summary["resource_use"] == {"runtime_seconds": 1.25, "peak_memory_mib": 64.0}


def test_acceptance_summary_separates_primary_fallback_range_and_joint_strata():
    cfg = config()
    budget = cfg.transfer_budget_ladder[0]

    def alternative(forecast_tier: str, range_tier: str) -> dict:
        return {
            "forecast_support_tier": forecast_tier,
            "receiver_range_evidence": range_tier,
            "baseline_receiver_state": {"cells": []},
            "transferred_expected_registrations_total": 14.0,
            "certify_up_steps": 0,
            "sensitivity_range_result": (
                "RANGE_EVIDENCE_INCOMPLETE" if range_tier == "RANGE_LIMITED" else "ROBUST_TO_TRANSFORMED_RANGE"
            ),
            "receiver_no_worse_constraint_satisfied": True,
            "receiver_range_masking_present": range_tier == "RANGE_LIMITED",
        }

    def unit(
        support: str,
        alternatives: list[dict],
        *,
        codes: list[str] | None = None,
        rejected_count: int = 0,
    ) -> dict:
        codes = codes or []
        return {
            "constraint_policy": {"max_transfer_fraction": budget},
            "donor_signal_ref": {"priority_support_class": support},
            "alternatives": alternatives,
            "abstention_status": {
                "abstained": not alternatives,
                "codes": codes,
                "rejected_receivers": [
                    {"receiver_hospital_id": f"rejected-{index}", "code": "RECEIVER_BLOCKED"}
                    for index in range(rejected_count)
                ],
            },
            "donor_minimum_transfer_fraction": 0.2,
            "donor_zero_threshold_binding_present": False,
            "alternatives_shortlisted": len(alternatives),
            "verification_failures": [],
            "alternatives_dropped_by_shortlist_bound": [],
        }

    rows = [
        unit("direct_supported", [alternative("DIRECT_SUPPORTED", "COMPLETE")]),
        unit("direct_supported", [alternative("DIRECT_SUPPORTED", "RANGE_LIMITED")]),
        unit("fallback_or_limited_history", [alternative("FALLBACK_LIMITED", "COMPLETE")]),
        unit("direct_supported", [], codes=["NO_ELIGIBLE_RECEIVER"], rejected_count=30),
    ]
    summary = _acceptance_summary(
        rows,
        cfg,
        unique_full_verifications=3,
        verification_cache_reuses=0,
        runtime_seconds=1.0,
        peak_memory=2.0,
    )["by_policy_budget"][format(budget, ".2f")]

    assert summary["units_evaluated"] == 4
    assert summary["units_with_at_least_one_published_alternative"] == 3
    assert summary["at_least_one_alternative_rate"] == 0.75
    assert summary["primary_units_evaluated"] == 3
    assert summary["primary_units_with_at_least_one_direct_complete_alternative"] == 1
    assert summary["primary_at_least_one_alternative_rate"] == pytest.approx(1 / 3)
    assert summary["fallback_units_evaluated"] == 1
    assert summary["fallback_units_with_at_least_one_alternative"] == 1
    assert summary["fallback_at_least_one_alternative_rate"] == 1.0
    assert summary["units_with_range_limited_alternative"] == 1
    assert summary["units_with_range_limited_alternative_rate"] == 0.25
    assert summary["range_limited_alternative_count"] == 1
    assert summary["range_limited_alternative_share"] == pytest.approx(1 / 3)
    assert summary["joint_evidence_stratum_composition"] == {
        "DIRECT_SUPPORTED|COMPLETE": 1,
        "DIRECT_SUPPORTED|RANGE_LIMITED": 1,
        "FALLBACK_LIMITED|COMPLETE": 1,
        "FALLBACK_LIMITED|RANGE_LIMITED": 0,
    }
    assert summary["unit_level_abstention_counts_by_reason"] == {"NO_ELIGIBLE_RECEIVER": 1}


def test_public_materiality_explanation_extension_codes_and_lexicon_contract():
    daily, entity, inbox = baseline_fixture()
    result = generate_decision_alternative_set(
        baseline_daily=daily,
        baseline_entity=entity,
        donor_signal=donor_signal(inbox),
        anomalies=anomaly_frame(),
        pressure_config=pressure_config(),
        prioritization_config=prioritization_config(),
        config=config(),
        max_transfer_fraction=1.0,
        provenance=public_provenance(),
    )
    alternative = next(item for item in result["alternatives"] if item["receiver"]["hospital_id"] == "h2")
    assert alternative["verification_only_fields"]["materiality_status"]["h2"] == "NOT_OBSERVED"
    explanation = alternative["explanation"]["text"]
    assert format(alternative["transferred_expected_registrations_total"], ".17g") in explanation
    assert "Receiver horizon" in explanation or "No receiver breakpoint" in explanation

    documentation = (ROOT / "docs" / "decision-alternatives-6b4.md").read_text()
    for code in (
        AbstentionCode.RECEIVER_OUTSIDE_SAME_REGION_POLICY.value,
        AbstentionCode.RECEIVER_NOT_ALLOW_LISTED.value,
    ):
        assert code in documentation

    for forbidden in ("route", "avoid overload"):
        invalid = json.loads(json.dumps(result))
        invalid["alternatives"][0]["explanation"]["text"] += f" {forbidden}"
        with pytest.raises(ValueError, match="prohibited wording"):
            assert_public_contract(invalid)
