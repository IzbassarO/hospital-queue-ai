"""Offline projection of accepted review evidence (stress tests, decision alternatives); never imported by the API.

No fitting, scenario execution, re-verification, ranking or severity calculation. Every value is copied from the
checksummed accepted artifacts of the frozen runs, and the identity scenario is later checked against the
published operational forecasts at publication time. See docs/demo-publication-slice-6.md.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.review_evidence import (  # noqa: E402
    AlternativeRow,
    AlternativeSetRow,
    ReviewEvidenceBundle,
    ScenarioCatalogRow,
    ScenarioCellRow,
    ScenarioEntityRow,
)
from app.services.review_evidence import parse_bundle  # noqa: E402


def _load_operational_builder():
    spec = importlib.util.spec_from_file_location("operational_bundle", ROOT / "tools" / "operational_bundle.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


operational = _load_operational_builder()
Evidence = operational.Evidence
canonical = operational.canonical
date = operational.date
evidence_hash = operational.evidence_hash
number = operational.number
require = operational.require
read_json = operational.read_json

ASSURANCE_IDENTITY = operational.ASSURANCE_IDENTITY
ORIGIN = operational.ORIGIN
OPERATIONAL_PUBLICATION = operational.PUBLICATION
PUBLICATION = "review-evidence-slice6-final-test-2025-03-17-v1"
SCENARIO_RUN = operational.SOURCES["flow_scenario"][1]
DECISION_RUN = operational.SOURCES["decision_alternatives"][1]
STANDARD_SCENARIOS = (
    "baseline-identity",
    "national-registrations-x0.90",
    "national-registrations-x1.10",
    "national-registrations-x1.20",
)
TARGET = "registrations"
LIMITATIONS = [
    "Retrospective final-test origin 2025-03-17; evaluation evidence, not a live forecast or current hospital "
    "condition.",
    "Forecast stress tests are deterministic non-causal sensitivity checks of the accepted registrations forecast; "
    "they are not a Digital Twin, causal simulator, intervention engine or capacity simulation.",
    "Scenario sensitivity ranges are derived from the accepted calibrated bounds by an additive central shift; "
    "they are not re-calibrated and carry no coverage guarantee.",
    "Decision alternatives are retrospective mathematical alternatives for human review; they are not "
    "recommendations, routing, optimization, capacity planning or a feasibility claim.",
    "Physical feasibility is unknown and physical capacity was not checked; the receiver threshold comparator is an "
    "assumption against an unchanged historical reference.",
    "Human review required; no autonomous action, promotion or causal effect claim.",
    "Freshness UNKNOWN: no approved refresh SLA; publication time is not evidence freshness.",
]
SCENARIO_LIMITATIONS = [
    "No causal identification; no capacity; no joint distribution; synthetic sensitivity bounds have no coverage "
    "guarantee.",
    "Inherited source reason codes describe the baseline severity rule; scenario severity was evaluated on the "
    "derived sensitivity range and is not evidence that scenario bounds were calibrated.",
]
SET_LIMITATION_CODES = {
    "NOT_PHYSICAL_CAPACITY_VALIDATED",
    "THRESHOLD_COMPARATOR_ASSUMPTION",
    "PHYSICAL_FEASIBILITY_UNKNOWN",
}
SEVERITY = {"HIGH", "ELEVATED", "WATCH", "NORMAL", "UNSUPPORTED"}
SUPPORT = {"DIRECT_SUPPORTED", "FALLBACK_LIMITED", "UNSUPPORTED"}


def evaluation_artifact(evidence: Evidence, run_id: str, run: dict) -> Path:
    """Locate the completed evaluation checkpoint artifact referenced by the accepted summary checkpoint."""
    artifact = run["artifacts"]["load_forecast"]
    checkpoints = []
    for path in sorted((evidence.root / "artifacts/runs" / run_id / "checkpoints").glob("*.json")):
        cp = evidence.json(path.relative_to(evidence.root).as_posix())
        expected = evidence_hash(
            {
                "run_scientific_identity": run["scientific_identity_sha256"],
                "key": cp["key"],
                "parameters": cp["parameters"],
            }
        )
        require(
            cp["scientific_identity_sha256"] == expected
            and cp["status"] == "completed"
            and cp["evaluation"]["status"] == "completed",
            f"checkpoint identity/status mismatch: {run_id}",
        )
        checkpoints.append(cp)
    summary_cp = [cp for cp in checkpoints if cp["artifact"] == artifact]
    require(len(summary_cp) == 1, f"missing/ambiguous summary checkpoint: {run_id}")
    evaluation_id = summary_cp[0]["parameters"]["evaluation_checkpoint"]
    candidates = [cp for cp in checkpoints if evidence_hash(cp["key"]) == evaluation_id]
    require(len(candidates) == 1, f"missing/ambiguous evaluation checkpoint: {run_id}")
    return evidence.artifact(candidates[0]["artifact"])


def severity(value) -> str:
    require(value in SEVERITY, f"unknown severity {value!r}")
    return str(value)


def optional_int(value) -> int | None:
    parsed = number(value)
    return None if parsed is None else int(parsed)


def scenario_catalog(spec: dict, summary: dict, validation: dict) -> dict:
    lever = spec["levers"]
    require(len(lever) == 1, "one lever per standard scenario")
    lever = lever[0]
    scenario = summary["scenario"]
    registrations = summary["targets"]["registrations"]
    daily = registrations["daily_cells"]
    entities = registrations["entities"]
    require(scenario["execution_mode"] == "EVALUATION" and scenario["serving_claim"] is False, "scenario mode")
    require(scenario["uncertainty"]["coverage_guarantee"] is False, "scenario range must not claim coverage")
    require(all(not lv["causal_effect_claimed"] for lv in scenario["levers"]), "causal claim in scenario")
    require(validation["scientific_output_sha256"] == validation["determinism"]["scientific_output_sha256"], "det")
    facts = [
        f"Verification: boundaries={validation['boundaries']['status']}; scope invariance="
        f"{validation['scope_invariance']['status']}; hierarchy coherent="
        f"{validation['hierarchy_coherence']['within_tolerance']}; raw quantiles untouched="
        f"{validation['raw_quantiles_untouched']}; cohort hospitalizations unchanged="
        f"{validation['cohort_hospitalizations_unchanged']}.",
        f"Ranking method: {scenario['ranking_method']}.",
        f"Primary Inbox under scenario: baseline size {registrations['inbox']['baseline_size']}, "
        f"scenario size {registrations['inbox']['scenario_size']}, entered {registrations['inbox']['entered']}, "
        f"left {registrations['inbox']['left']}.",
    ]
    return ScenarioCatalogRow.model_validate(
        {
            "scenario_id": spec["scenario_id"],
            "scenario_type": spec["scenario_type"],
            "classification": spec["classification"],
            "lever_type": lever["lever_type"],
            "multiplier": lever.get("parameters", {}).get("multiplier"),
            "scope_type": spec["scope"]["scope_type"],
            "horizon_start": spec["scope"]["horizon_start"],
            "horizon_end": spec["scope"]["horizon_end"],
            "target": summary["primary_target"],
            "uncertainty_method": scenario["uncertainty"]["method"],
            "uncertainty_label": scenario["uncertainty"]["label"],
            "coverage_guarantee": False,
            "causal_effect_claimed": False,
            "serving_claim": False,
            "baseline_reproduction": "PASS" if spec["scenario_type"] == "identity" else None,
            "network_summary": {
                "daily_cells_total": daily["total"],
                "severity_changed_count": daily["severity_changed_count"],
                "severity_changed_share": daily["severity_changed_share"],
                "severity_counts": daily["severity_counts"],
                "entity_count": entities["total"],
                "entity_severity_changed_count": entities["changed_count"],
            },
            "evidence_facts": facts,
            "limitations": SCENARIO_LIMITATIONS,
        }
    ).model_dump(mode="json")


def entity_row(scenario_id: str, diff: dict, signal: dict, inbox: dict | None) -> dict:
    return ScenarioEntityRow.model_validate(
        {
            "scenario_id": scenario_id,
            "series_id": signal["series_id"],
            "origin": date(diff["origin"]),
            "target": diff["target"],
            "org_code": diff["hospital_id"],
            "region_code": signal["region_id"],
            "profile_code": diff["profile_id"],
            "signal_id": signal["signal_id"],
            "baseline_severity": severity(diff["baseline_severity"]),
            "scenario_severity": severity(diff["scenario_severity"]),
            "baseline_inbox_rank": optional_int(diff["baseline_inbox_rank"]),
            "scenario_inbox_rank": optional_int(diff["scenario_inbox_rank"]),
            "baseline_central": number(diff["baseline_central"]),
            "scenario_central": number(diff["scenario_central"]),
            "threshold_value": number(diff["scenario_threshold"]),
            "absolute_delta": number(diff["absolute_delta"]),
            "relative_delta": number(diff["relative_delta"]),
            "severity_changed": bool(diff["severity_changed"]),
            "entered_primary_inbox": bool(diff["entered_primary_inbox"]),
            "left_primary_inbox": bool(diff["left_primary_inbox"]),
            "first_crossing_date": date(signal["first_crossing_date"]),
            "lead_time_days": optional_int(signal["lead_time_days"]),
            "materiality_status": inbox["materiality_status"] if inbox else None,
            "scenario_headline": inbox["headline"] if inbox else None,
            "scenario_reason": inbox["concise_reason"] if inbox else None,
            "scenario_range_available": bool(signal["scenario_uncertainty_status"] != "UNAVAILABLE"),
            "limitations": SCENARIO_LIMITATIONS,
        }
    ).model_dump(mode="json")


def cell_row(scenario_id: str, diff: dict, cell: dict) -> dict:
    status = cell["scenario_uncertainty_status"]
    baseline_bounds = cell["baseline_uncertainty_status"] in {
        "level_local_calibrated",
        "level_local_calibrated_not_reconciled",
    }
    lower, upper = number(cell["baseline_uncertainty_lower"]), number(cell["baseline_uncertainty_upper"])
    s_lower, s_upper = number(cell["scenario_sensitivity_lower"]), number(cell["scenario_sensitivity_upper"])
    if status == "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE":
        require(s_lower is not None and s_upper is not None, "transformed range without bounds")
    else:
        s_lower = s_upper = None
    require(cell["scenario_calibration_status"] == "baseline_only_not_scenario", "scenario must not claim calibration")
    require(cell["scenario_range_coverage_guarantee"] is False, "scenario range must not claim coverage")
    return ScenarioCellRow.model_validate(
        {
            "scenario_id": scenario_id,
            "series_id": diff["series_id"],
            "origin": date(diff["origin"]),
            "target": diff["target"],
            "target_date": date(diff["target_date"]),
            "horizon": int(diff["horizon"]),
            "baseline_central": number(diff["baseline_central"]),
            "baseline_lower": lower if baseline_bounds else None,
            "baseline_upper": upper if baseline_bounds else None,
            "baseline_severity": severity(diff["baseline_severity"]),
            "scenario_central": number(diff["scenario_central"]),
            "scenario_lower": s_lower,
            "scenario_upper": s_upper,
            "scenario_severity": severity(diff["scenario_severity"]),
            "threshold_value": number(diff["scenario_threshold"]),
            "threshold_status": cell["threshold_status"],
            "scenario_uncertainty_status": status,
            "severity_changed": bool(diff["severity_changed"]),
            "source_reason_code": cell["source_reason_code"],
        }
    ).model_dump(mode="json")


def state(source: dict) -> dict:
    return {
        "displayed_severity": severity(source["displayed_severity"]),
        "max_severity_7d": severity(source["max_severity_7d"]),
        "max_severity_14d": severity(source["max_severity_14d"]),
        "severity_evidence_horizon": source.get("severity_evidence_horizon"),
        "severity_evidence_date": source.get("severity_evidence_date"),
        "cells": [
            {
                "horizon": c["horizon"],
                "target_date": c["target_date"],
                "central": c["central"],
                "lower": c.get("sensitivity_lower"),
                "upper": c.get("sensitivity_upper"),
                "severity": severity(c["severity"]),
                "threshold_value": c.get("threshold_value"),
                "threshold_status": c.get("threshold_status"),
            }
            for c in source["cells"]
        ],
    }


def series_ref(source: dict) -> dict:
    return {
        "org_code": source["hospital_id"],
        "profile_code": source["profile_id"],
        "region_code": source["region_id"],
        "series_id": source["series_id"],
    }


def alternative(source: dict) -> dict:
    fields = source["verification_only_fields"]
    inbox = {
        key: {
            "baseline_inbox_rank": fields[key]["baseline_inbox_rank"],
            "scenario_inbox_rank": fields[key]["scenario_inbox_rank"],
            "baseline_severity": severity(fields[key]["baseline_severity"]),
            "scenario_severity": severity(fields[key]["scenario_severity"]),
            "entered_primary_inbox": fields[key]["entered_primary_inbox"],
            "left_primary_inbox": fields[key]["left_primary_inbox"],
        }
        for key in ("donor_inbox", "receiver_inbox")
    }
    require(source["execution_mode"] == "EVALUATION" and source["serving_claim"] is False, "alternative mode")
    require(source["range_recalibrated"] is False and source["coverage_guarantee"] is False, "alternative range")
    return AlternativeRow.model_validate(
        {
            "alternative_id": source["alternative_id"],
            "donor": series_ref(source["donor"]),
            "receiver": series_ref(source["receiver"]),
            "transfer_fraction": source["transfer_fraction"],
            "transfer_fraction_certification": source["transfer_fraction_certification"],
            "transferred_total": source["transferred_expected_registrations_total"],
            "transferred_by_horizon": source["transferred_by_horizon"],
            "donor_severity_before": severity(source["baseline_donor_state"]["displayed_severity"]),
            "donor_severity_after": severity(source["donor_severity_after"]),
            "receiver_severity_before": severity(source["baseline_receiver_state"]["displayed_severity"]),
            "receiver_severity_after": severity(source["receiver_worst_severity_after"]),
            "donor_binding_horizons": source["donor_binding_horizons"],
            "donor_binding_cell": source["donor_binding_cell"],
            "receiver_binding_cell": source["receiver_binding_cell"],
            "receiver_min_central_headroom": source["receiver_min_central_headroom"],
            "receiver_no_worse_constraint_satisfied": source["receiver_no_worse_constraint_satisfied"],
            "conservation_satisfied": source["conservation_satisfied"],
            "budget_constraint_satisfied": source["budget_constraint_satisfied"],
            "source_central_goal_satisfied": source["source_central_goal_satisfied"],
            "verification_state": source["verification_state"],
            "forecast_support_tier": source["forecast_support_tier"],
            "donor_support_class": source["donor_support_class"],
            "receiver_support_class": source["receiver_support_class"],
            "receiver_range_evidence": source["receiver_range_evidence"],
            "sensitivity_range_result": source["sensitivity_range_result"],
            "feasibility_status": source["feasibility_status"],
            "capacity_checked": source["capacity_checked"],
            "causal_effect_claimed": source["causal_effect_claimed"],
            "human_review_required": source["human_review_required"],
            "hierarchy_coherent": bool(fields["hierarchy_coherence"]["within_tolerance"]),
            **inbox,
            "explanation_text": source["explanation"]["text"],
            "non_claims": source["explanation"]["non_claims"],
            "limitations": source["limitations"],
            "baseline_donor_state": state(source["baseline_donor_state"]),
            "scenario_donor_state": state(source["scenario_donor_state"]),
            "baseline_receiver_state": state(source["baseline_receiver_state"]),
            "scenario_receiver_state": state(source["scenario_receiver_state"]),
        }
    ).model_dump(mode="json")


def alternative_set(source: dict, region_lookup: dict[tuple[str, str, str], tuple[str, str, int | None]]) -> dict:
    donor = source["donor_signal_ref"]
    require(source["execution_mode"] == "EVALUATION" and source["serving_claim"] is False, "set mode")
    require(source["human_review_required"] is True, "set must require human review")
    require(source["target"] == "REGISTRATIONS", "unexpected decision target")
    require(set(source["limitations"]) >= SET_LIMITATION_CODES, "missing mandatory set limitation codes")
    key = (donor["hospital_id"], donor["profile_id"], donor["origin"])
    require(key in region_lookup, f"donor without accepted baseline entity: {key}")
    region_code, series_id, inbox_rank = region_lookup[key]
    rejected = Counter(r["code"] for r in source["abstention_status"]["rejected_receivers"])
    budget = source["constraint_policy"]["max_transfer_fraction"]
    return AlternativeSetRow.model_validate(
        {
            "set_id": f"{source['canonical_unit_id']}-{budget:.2f}",
            "canonical_unit_id": source["canonical_unit_id"],
            "origin": donor["origin"],
            "target": TARGET,
            "donor": {
                "signal_id": donor["signal_id"],
                "org_code": donor["hospital_id"],
                "profile_code": donor["profile_id"],
                "region_code": region_code,
                "series_id": series_id,
                "displayed_severity": severity(donor["displayed_severity"]),
                "priority_support_class": donor["priority_support_class"],
                "materiality_status": donor["materiality_status"],
                "binding_horizons": donor["binding_horizons"],
                "inbox_rank": inbox_rank,
            },
            "budget": budget,
            "abstained": bool(source["abstention_status"]["abstained"]),
            "abstention_codes": source["abstention_status"]["codes"]
            if source["abstention_status"]["abstained"]
            else [],
            "rejected_receiver_counts": dict(sorted(rejected.items())),
            "receiver_candidates_considered": source["receiver_candidates_considered"],
            "receiver_candidates_eligible": source["receiver_candidates_eligible"],
            "donor_minimum_transfer_fraction": source["donor_minimum_transfer_fraction"],
            "shortlist_bound": source["shortlist_bound"],
            "alternatives": [alternative(a) for a in source["alternatives"]],
            "verification_failure_count": len(source["verification_failures"]),
            "scientific_output_sha256": source["scientific_output_sha256"],
            "execution_mode": "EVALUATION",
            "human_review_required": True,
            "serving_claim": False,
            "limitations": source["limitations"],
        }
    ).model_dump(mode="json")


def build(root: Path) -> tuple[dict, dict]:
    import pandas as pd

    evidence = Evidence(root)
    assurance, provenance, summaries, _ = evidence.verify()
    capabilities = {c["capability_id"]: c for c in assurance["capabilities"]}
    for capability_id in ("forecast_stress_test", "decision_alternatives"):
        cap = capabilities[capability_id]
        require(cap["product_consumption_status"] == "EVALUATION_ONLY", "review sources must be evaluation-only")
        require(cap["governance"]["promotion_status"] == "NO_PROMOTION", "review sources must not be promoted")
    operational_report = read_json(
        root / "artifacts/operational_intelligence" / OPERATIONAL_PUBLICATION / "build-report.json"
    )
    require(operational_report["assurance_identity_sha256"] == ASSURANCE_IDENTITY, "operational assurance identity")
    operational_identity = operational_report["publication_identity_sha256"]
    print("Verified accepted runs, summary identities and Model Assurance", flush=True)

    scenario_run = evidence.json(f"artifacts/runs/{SCENARIO_RUN}/run.json")
    scenario_eval = evaluation_artifact(evidence, SCENARIO_RUN, scenario_run)
    scenario_summary = read_json(scenario_eval / "scenario-summary.json")
    validation = read_json(scenario_eval / "validation.json")
    require(validation["baseline_reproduction"]["status"] == "PASS", "baseline reproduction did not pass")
    require(scenario_summary["run_id"] == SCENARIO_RUN, "scenario evaluation run mismatch")
    require(
        summaries["flow_scenario"]["source_lineage"]["hierarchy"]["source_run_id"]
        == provenance["flow_hierarchy"]["run_id"]
        and summaries["flow_scenario"]["source_lineage"]["hierarchy"]["source_scientific_identity"]
        == provenance["flow_hierarchy"]["scientific_identity_sha256"],
        "scenario run is not based on the accepted hierarchy run",
    )
    require(
        tuple(scenario_summary["protocol"]["scenario_ids"]) == STANDARD_SCENARIOS,
        "unexpected standard scenario suite",
    )
    by_scenario = {s["scenario"]["scenario_id"]: s for s in scenario_summary["scenarios"]}
    print("Verified scenario evaluation artifact and standard suite", flush=True)

    # Population rule: every primary-Inbox registrations entity at the explicit final-test origin (no selection).
    identity_signals = pd.read_parquet(
        scenario_eval / "scenarios/baseline-identity/entity-signals.parquet",
        filters=[("phase", "==", "final_test"), ("target", "==", TARGET)],
    )
    identity_diff = pd.read_parquet(
        scenario_eval / "scenarios/baseline-identity/entity-differences.parquet",
        filters=[("phase", "==", "final_test"), ("target", "==", TARGET)],
    )
    population = identity_diff[identity_diff.baseline_inbox_rank.notna()]
    require(set(population.origin.map(date)) == {ORIGIN}, "unexpected scenario origin")
    keys = {(r["hospital_id"], r["profile_id"]) for r in population.to_dict("records")}
    ranks = sorted(int(r) for r in population.baseline_inbox_rank)
    require(ranks == list(range(1, len(ranks) + 1)), "primary Inbox ranks are not a complete canonical sequence")
    signals_by_key = {
        (r["hospital_id"], r["profile_id"]): r
        for r in identity_signals.to_dict("records")
        if (r["hospital_id"], r["profile_id"]) in keys
    }
    require(len(signals_by_key) == len(keys), "entity without baseline signal row")
    all_signals = pd.read_parquet(
        scenario_eval / "scenarios/baseline-identity/entity-signals.parquet",
        columns=["hospital_id", "profile_id", "origin", "region_id", "series_id", "target"],
        filters=[("target", "==", TARGET)],
    )
    all_ranks = pd.read_parquet(
        scenario_eval / "scenarios/baseline-identity/entity-differences.parquet",
        columns=["hospital_id", "profile_id", "origin", "baseline_inbox_rank", "target"],
        filters=[("target", "==", TARGET)],
    )
    rank_lookup = {
        (r["hospital_id"], r["profile_id"], date(r["origin"])): optional_int(r["baseline_inbox_rank"])
        for r in all_ranks.to_dict("records")
    }
    region_lookup = {
        (r["hospital_id"], r["profile_id"], date(r["origin"])): (
            r["region_id"],
            r["series_id"],
            rank_lookup.get((r["hospital_id"], r["profile_id"], date(r["origin"]))),
        )
        for r in all_signals.to_dict("records")
    }

    scenarios, entities, cells = [], [], []
    for scenario_id in STANDARD_SCENARIOS:
        directory = scenario_eval / "scenarios" / scenario_id
        spec = read_json(directory / "spec.json")
        scenarios.append(scenario_catalog(spec, by_scenario[scenario_id], validation["scenarios"][scenario_id]))
        diff = pd.read_parquet(
            directory / "entity-differences.parquet", filters=[("phase", "==", "final_test"), ("target", "==", TARGET)]
        )
        diff = diff[[(h, p) in keys for h, p in zip(diff.hospital_id, diff.profile_id, strict=True)]]
        require(len(diff) == len(keys), f"partial entity population: {scenario_id}")
        signal_rows = pd.read_parquet(
            directory / "entity-signals.parquet", filters=[("phase", "==", "final_test"), ("target", "==", TARGET)]
        )
        scenario_signals = {
            (r["hospital_id"], r["profile_id"]): r
            for r in signal_rows.to_dict("records")
            if (r["hospital_id"], r["profile_id"]) in keys
        }
        inbox_rows = pd.read_parquet(directory / "inbox.parquet", filters=[("phase", "==", "final_test")])
        inbox = {(r["hospital_id"], r["profile_id"]): r for r in inbox_rows.to_dict("records")}
        for row in diff.sort_values(["hospital_id", "profile_id"]).to_dict("records"):
            key = (row["hospital_id"], row["profile_id"])
            signal = scenario_signals[key]
            require(signal["signal_id"] == signals_by_key[key]["signal_id"], "signal identity changed under scenario")
            require(signal["region_id"] == signals_by_key[key]["region_id"], "region changed under scenario")
            entities.append(entity_row(scenario_id, row, signal, inbox.get(key)))
        daily = pd.read_parquet(
            directory / "daily-differences.parquet", filters=[("phase", "==", "final_test"), ("target", "==", TARGET)]
        )
        series_ids = {signals_by_key[k]["series_id"] for k in keys}
        daily = daily[daily.series_id.isin(series_ids)]
        require(len(daily) == 14 * len(keys), f"partial daily population: {scenario_id}")
        scenario_cells = pd.read_parquet(
            directory / "scenario-cells.parquet",
            columns=[
                "series_id",
                "target_date",
                "baseline_uncertainty_status",
                "baseline_uncertainty_lower",
                "baseline_uncertainty_upper",
                "scenario_sensitivity_lower",
                "scenario_sensitivity_upper",
                "scenario_uncertainty_status",
                "scenario_calibration_status",
                "scenario_range_coverage_guarantee",
                "threshold_status",
                "source_reason_code",
            ],
            filters=[("phase", "==", "final_test"), ("target", "==", TARGET), ("level", "==", "hospital")],
        )
        scenario_cells = scenario_cells[scenario_cells.series_id.isin(series_ids)]
        cell_lookup = {(r["series_id"], date(r["target_date"])): r for r in scenario_cells.to_dict("records")}
        require(len(cell_lookup) == len(daily), f"scenario cell/daily difference mismatch: {scenario_id}")
        for row in daily.sort_values(["series_id", "target_date"]).to_dict("records"):
            cells.append(cell_row(scenario_id, row, cell_lookup[(row["series_id"], date(row["target_date"]))]))
        print(f"Projected scenario {scenario_id}: {len(diff)} entities, {len(daily)} daily cells", flush=True)

    decision_run = evidence.json(f"artifacts/runs/{DECISION_RUN}/run.json")
    decision_eval = evaluation_artifact(evidence, DECISION_RUN, decision_run)
    decision_summary = read_json(decision_eval / "decision-alternatives-summary.json")
    require(decision_summary["run_id"] == DECISION_RUN, "decision evaluation run mismatch")
    lineage = summaries["decision_alternatives"]["source_lineage"]["scenario"]
    require(
        lineage["source_run_id"] == SCENARIO_RUN
        and lineage["source_scientific_identity"] == provenance["flow_scenario"]["scientific_identity_sha256"],
        "decision alternatives are not based on the accepted scenario run",
    )
    set_files = sorted((decision_eval / "alternative-sets").glob("*.json"))
    require(len(set_files) == decision_summary["alternative_set_count"], "alternative set count mismatch")
    sets = []
    for path in set_files:
        source = read_json(path)
        require(
            source["provenance"]["scenario_scientific_identity"]
            == provenance["flow_scenario"]["scientific_identity_sha256"]
            and source["provenance"]["code_identity_sha256"]
            == provenance["decision_alternatives"]["code_identity_sha256"],
            f"alternative set lineage mismatch: {path.name}",
        )
        sets.append(alternative_set(source, region_lookup))
    sets.sort(key=lambda r: (r["origin"], r["donor"]["signal_id"], r["budget"]))
    metrics = capabilities["decision_alternatives"]["evidence"]["key_metrics"]
    alternatives_summary = {
        "set_count": len(sets),
        "unit_count": len({(r["origin"], r["donor"]["signal_id"]) for r in sets}),
        "sets_with_alternatives": sum(1 for r in sets if r["alternatives"]),
        "alternative_count": sum(len(r["alternatives"]) for r in sets),
        "receiver_worsening_count": metrics["receiver_worsening_count"],
        "verification_failure_count": metrics["full_verification_failures"],
        "full_verification_success_rate": metrics["full_verification_success_rate"],
        "transfer_budget_ladder": decision_summary["protocol"]["transfer_budget_ladder"],
        "origins": decision_summary["protocol"]["origins"],
        "evaluation_population": capabilities["decision_alternatives"]["evidence"]["evaluation_population"],
    }
    require(alternatives_summary["receiver_worsening_count"] == 0, "accepted evidence reports receiver worsening")
    print(
        f"Projected {len(sets)} alternative sets ({alternatives_summary['alternative_count']} alternatives)", flush=True
    )

    payload = {
        "schema_version": "review_evidence_v1",
        "contract_version": "1.0.0",
        "publication_id": PUBLICATION,
        "publication_identity_sha256": "0" * 64,
        "assurance_identity_sha256": ASSURANCE_IDENTITY,
        "operational_publication_identity_sha256": operational_identity,
        "source_code_commit": assurance["source_code_commit"],
        "current_origin": ORIGIN,
        "freshness_state": "UNKNOWN",
        "publication_status": "AVAILABLE",
        "generated_at": None,
        "source_provenance": {
            key: provenance[key]
            for key in (
                "flow_scenario",
                "decision_alternatives",
                "flow_hierarchy",
                "flow_pressure",
                "signal_prioritization",
            )
        },
        "limitations": LIMITATIONS,
        "scenarios": scenarios,
        "scenario_entities": entities,
        "scenario_cells": cells,
        "alternative_sets": sets,
        "alternatives_summary": alternatives_summary,
    }
    validated = ReviewEvidenceBundle.model_validate(payload).model_dump(mode="json")
    identity = {k: v for k, v in validated.items() if k not in {"publication_identity_sha256", "generated_at"}}
    validated["publication_identity_sha256"] = hashlib.sha256(canonical(identity)).hexdigest()
    parse_bundle(canonical(validated))
    report = {
        "builder_version": "frozen-review-evidence-projection-v1",
        "publication_identity_sha256": validated["publication_identity_sha256"],
        "assurance_identity_sha256": ASSURANCE_IDENTITY,
        "operational_publication_identity_sha256": operational_identity,
        "source_provenance": payload["source_provenance"],
        "verified_files": evidence.files,
        "population_rule": "every primary-Inbox registrations entity at the explicit final-test origin, all standard "
        "scenarios; every accepted alternative set of the frozen decision-alternatives run",
        "scenario_count": len(scenarios),
        "scenario_entity_count": len(entities),
        "scenario_cell_count": len(cells),
        "alternatives_summary": alternatives_summary,
    }
    return validated, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    bundle, report = build(args.root)
    output = args.root / "artifacts/review_evidence" / PUBLICATION
    output.mkdir(parents=True, exist_ok=True)
    for name, value in [("review_evidence.json", bundle), ("build-report.json", report)]:
        path = output / name
        data = canonical(value) + b"\n"
        if path.exists():
            require(path.read_bytes() == data, f"immutable output already exists with different content: {name}")
        else:
            temporary = path.with_suffix(".json.partial")
            temporary.write_bytes(data)
            temporary.replace(path)
    print(
        json.dumps(
            {
                "output": str(output),
                "scenario_cells": report["scenario_cell_count"],
                "alternative_sets": report["alternatives_summary"]["set_count"],
                "identity": bundle["publication_identity_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
