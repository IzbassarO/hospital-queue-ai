"""Offline review-evidence projection controls; small synthetic records, no real artifact dependency."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("review_bundle", ROOT / "tools/review_evidence_bundle.py")
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def daily_difference(**overrides):
    return {
        "series_id": "hp:H001:P01",
        "origin": "2025-03-17",
        "target": "registrations",
        "target_date": "2025-03-18",
        "horizon": 1,
        "baseline_central": 5.0,
        "baseline_severity": "HIGH",
        "scenario_central": 6.0,
        "scenario_severity": "HIGH",
        "scenario_threshold": 1.0,
        "severity_changed": False,
    } | overrides


def scenario_cell(**overrides):
    return {
        "baseline_uncertainty_status": "level_local_calibrated",
        "baseline_uncertainty_lower": 1.0,
        "baseline_uncertainty_upper": 20.0,
        "scenario_sensitivity_lower": 2.0,
        "scenario_sensitivity_upper": 21.0,
        "scenario_uncertainty_status": "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE",
        "scenario_calibration_status": "baseline_only_not_scenario",
        "scenario_range_coverage_guarantee": False,
        "threshold_status": "supported",
        "source_reason_code": "CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD",
    } | overrides


def test_cell_keeps_accepted_bounds_and_derived_range_separate():
    row = builder.cell_row("x1.20", daily_difference(), scenario_cell())
    assert (row["baseline_lower"], row["baseline_upper"]) == (1.0, 20.0)
    assert (row["scenario_lower"], row["scenario_upper"]) == (2.0, 21.0)
    assert row["scenario_uncertainty_status"] == "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE"


def test_cell_without_usable_uncertainty_publishes_no_range_and_no_baseline_bounds():
    row = builder.cell_row(
        "x1.20",
        daily_difference(),
        scenario_cell(
            baseline_uncertainty_status="calibration_support_insufficient",
            scenario_uncertainty_status="UNAVAILABLE",
            scenario_sensitivity_lower=None,
            scenario_sensitivity_upper=None,
        ),
    )
    assert row["baseline_lower"] is None and row["scenario_lower"] is None
    assert row["scenario_uncertainty_status"] == "UNAVAILABLE"


def test_cell_rejects_a_scenario_that_claims_calibration_or_coverage():
    with pytest.raises(ValueError, match="must not claim calibration"):
        builder.cell_row("x", daily_difference(), scenario_cell(scenario_calibration_status="calibrated"))
    with pytest.raises(ValueError, match="must not claim coverage"):
        builder.cell_row("x", daily_difference(), scenario_cell(scenario_range_coverage_guarantee=True))
    with pytest.raises(ValueError, match="unknown severity"):
        builder.cell_row("x", daily_difference(baseline_severity="CRITICAL"), scenario_cell())


def abstained_set():
    return {
        "abstention_status": {
            "abstained": True,
            "codes": ["RECEIVER_BLOCKED"],
            "rejected_receivers": [
                {"code": "RECEIVER_OUTSIDE_SAME_REGION_POLICY", "receiver_hospital_id": "A"},
                {"code": "RECEIVER_BLOCKED", "receiver_hospital_id": "B"},
                {"code": "RECEIVER_BLOCKED", "receiver_hospital_id": "C"},
            ],
        },
        "alternatives": [],
        "canonical_unit_id": "unit",
        "constraint_policy": {"max_transfer_fraction": 0.25},
        "donor_minimum_transfer_fraction": 0.88,
        "donor_signal_ref": {
            "binding_horizons": [1, 2],
            "displayed_severity": "HIGH",
            "hospital_id": "000V",
            "materiality_status": "materiality_rule_not_triggered",
            "origin": "2025-03-17",
            "priority_support_class": "direct_supported",
            "profile_id": "391",
            "signal_id": "cc50",
            "target": "REGISTRATIONS",
        },
        "execution_mode": "EVALUATION",
        "human_review_required": True,
        "limitations": [
            "NOT_PHYSICAL_CAPACITY_VALIDATED",
            "THRESHOLD_COMPARATOR_ASSUMPTION",
            "PHYSICAL_FEASIBILITY_UNKNOWN",
        ],
        "receiver_candidates_considered": 61,
        "receiver_candidates_eligible": 4,
        "scientific_output_sha256": "a" * 64,
        "serving_claim": False,
        "shortlist_bound": 5,
        "target": "REGISTRATIONS",
        "verification_failures": [],
    }


def test_abstained_set_is_published_with_reasons_and_region_from_accepted_baseline():
    lookup = {("000V", "391", "2025-03-17"): ("39", "hp:000V:391", 1)}
    row = builder.alternative_set(abstained_set(), lookup)
    assert row["set_id"] == "unit-0.25" and row["abstained"] is True
    assert row["rejected_receiver_counts"] == {"RECEIVER_BLOCKED": 2, "RECEIVER_OUTSIDE_SAME_REGION_POLICY": 1}
    assert row["donor"]["region_code"] == "39" and row["donor"]["series_id"] == "hp:000V:391"
    assert row["donor"]["inbox_rank"] == 1
    assert row["alternatives"] == []


def test_set_fails_closed_on_missing_baseline_entity_or_limitation_codes():
    with pytest.raises(ValueError, match="without accepted baseline entity"):
        builder.alternative_set(abstained_set(), {})
    incomplete = abstained_set() | {"limitations": ["NOT_PHYSICAL_CAPACITY_VALIDATED"]}
    with pytest.raises(ValueError, match="mandatory set limitation codes"):
        builder.alternative_set(incomplete, {("000V", "391", "2025-03-17"): ("39", "hp:000V:391", 1)})
    serving = abstained_set() | {"serving_claim": True}
    with pytest.raises(ValueError, match="set mode"):
        builder.alternative_set(serving, {("000V", "391", "2025-03-17"): ("39", "hp:000V:391", 1)})


def test_scenario_catalog_copies_population_counts_and_rejects_coverage_claims():
    spec = {
        "scenario_id": "national-registrations-x1.20",
        "scenario_type": "demand_multiplier",
        "classification": "SAFE_NON_CAUSAL_STRESS_TEST",
        "levers": [{"lever_type": "demand_multiplier", "parameters": {"multiplier": 1.2}}],
        "scope": {"scope_type": "all_hospitals", "horizon_start": 1, "horizon_end": 14},
    }
    summary = {
        "primary_target": "registrations",
        "scenario": {
            "execution_mode": "EVALUATION",
            "serving_claim": False,
            "ranking_method": "fixed_lexicographic_no_learned_or_weighted_score",
            "uncertainty": {
                "coverage_guarantee": False,
                "label": "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE",
                "method": "additive_central_shift_v1",
            },
            "levers": [{"causal_effect_claimed": False}],
        },
        "targets": {
            "registrations": {
                "daily_cells": {
                    "total": 366072,
                    "severity_changed_count": 37695,
                    "severity_changed_share": 0.103,
                    "severity_counts": {"HIGH": 26094},
                },
                "entities": {"total": 26148, "changed_count": 4360},
                "inbox": {"baseline_size": 7253, "scenario_size": 8845, "entered": 1593, "left": 1},
            }
        },
    }
    validation = {
        "scientific_output_sha256": "s",
        "determinism": {"scientific_output_sha256": "s"},
        "boundaries": {"status": "PASS"},
        "scope_invariance": {"status": "PASS"},
        "hierarchy_coherence": {"within_tolerance": True},
        "raw_quantiles_untouched": True,
        "cohort_hospitalizations_unchanged": True,
    }
    row = builder.scenario_catalog(spec, summary, validation)
    assert row["multiplier"] == 1.2 and row["baseline_reproduction"] is None
    assert row["network_summary"]["severity_changed_count"] == 37695
    assert row["network_summary"]["entity_count"] == 26148
    summary["scenario"]["uncertainty"]["coverage_guarantee"] = True
    with pytest.raises(ValueError, match="must not claim coverage"):
        builder.scenario_catalog(spec, summary, validation)
