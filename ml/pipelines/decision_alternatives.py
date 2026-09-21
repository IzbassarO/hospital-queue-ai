#!/usr/bin/env python3
"""Generate retrospective constrained decision alternatives from accepted flow evidence."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from hqai_ml.registry.resources import apply_resource_environment, resource_config

STARTED = time.perf_counter()


def log(message: str) -> None:
    print(f"[{time.perf_counter() - STARTED:7.1f}s] {message}", flush=True)


def peak_memory_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform != "darwin":
        value *= 1024
    return value / 1024**2


def decision_protocol(config) -> dict:
    return {
        "optimizer_contract_version": config.optimizer_contract_version,
        "scenario_contract_version": config.scenario_contract_version,
        "execution_mode": "EVALUATION",
        "serving_claim": False,
        "target": "registrations",
        "horizons": list(range(1, 15)),
        "top_n_primary_donors": config.donor_cohort.top_n_primary_donors,
        "top_n_fallback_donors": config.donor_cohort.top_n_fallback_donors,
        "origins": [value.isoformat() for value in config.donor_cohort.origins],
        "transfer_budget_ladder": config.transfer_budget_ladder,
        "shortlist_max_alternatives": config.shortlist_max_alternatives,
        "full_scenario_verification_required": True,
        "human_review_required": True,
        "physical_feasibility_validated": False,
        "real_data_acceptance_run": False,
    }


def decision_evaluation_key(version: str):
    from hqai_ml.registry.experiment import CheckpointKey

    return CheckpointKey(
        "load_forecast",
        candidate_id="constrained-decision-alternatives",
        trial_id=version,
        fold_id="precommitted-cohort",
    )


def _selected_donors(inbox, config):
    import pandas as pd

    origins = {pd.Timestamp(value) for value in config.donor_cohort.origins}
    selected = inbox[
        inbox["origin"].isin(origins)
        & inbox["target"].eq("registrations")
        & inbox["operational_priority_status"].eq("primary_inbox_eligible")
        & inbox["source_severity"].isin(config.donor_cohort.severities)
    ].copy()
    if not config.donor_cohort.include_fallback_tier_separately:
        selected = selected[selected["priority_support_class"].eq("direct_supported")]
    selected = selected.sort_values(
        ["origin", "priority_support_class", "inbox_rank", "region_id", "hospital_id", "profile_id"],
        kind="stable",
    )
    direct = (
        selected[selected["priority_support_class"].eq("direct_supported")]
        .groupby("origin", sort=True, observed=True)
        .head(config.donor_cohort.top_n_primary_donors)
    )
    fallback = (
        selected[selected["priority_support_class"].eq("fallback_or_limited_history")]
        .groupby("origin", sort=True, observed=True)
        .head(config.donor_cohort.top_n_fallback_donors)
    )
    return pd.concat([direct, fallback], ignore_index=True).sort_values(
        ["origin", "priority_support_class", "inbox_rank", "region_id", "hospital_id", "profile_id"],
        kind="stable",
    )


def _require_nonempty_donors(donors) -> None:
    if donors.empty:
        raise ValueError("ZERO_SELECTED_DONOR_UNITS: the precommitted donor cohort selected no units")


def _require_donor_daily_integrity(donors, daily) -> None:
    """Fail when the selected cohort cannot join to any expected donor daily rows."""
    matched_units = 0
    for donor in donors.itertuples(index=False):
        matched = daily[
            daily["target"].eq("registrations")
            & daily["level"].eq("hospital")
            & daily["phase"].eq(donor.phase)
            & daily["origin"].eq(donor.origin)
            & daily["region_id"].astype(str).eq(str(donor.region_id))
            & daily["profile_id"].astype(str).eq(str(donor.profile_id))
            & daily["hospital_id"].astype(str).eq(str(donor.hospital_id))
        ]
        matched_units += int(not matched.empty)
    if len(donors) and matched_units == 0:
        raise ValueError(
            "DONOR_DAILY_INPUT_JOIN_FAILED: selected donor units exist but none match registration daily rows"
        )


def _verification_plan_estimate(donors, daily, config) -> dict:
    """Return a read-only upper-bound estimate without executing the scenario engine."""
    receiver_candidates = 0
    for donor in donors.itertuples(index=False):
        peers = daily[
            daily["target"].eq("registrations")
            & daily["level"].eq("hospital")
            & daily["phase"].eq(donor.phase)
            & daily["origin"].eq(donor.origin)
            & daily["region_id"].astype(str).eq(str(donor.region_id))
            & daily["profile_id"].astype(str).eq(str(donor.profile_id))
            & daily["hospital_id"].astype(str).ne(str(donor.hospital_id))
        ]
        if config.receiver_policy.eligible_receiver_ids is not None:
            peers = peers[peers["hospital_id"].astype(str).isin(config.receiver_policy.eligible_receiver_ids)]
        peers = peers["hospital_id"].nunique()
        receiver_candidates += int(peers)
    evidence_strata = 4
    unique_upper_bound = min(
        receiver_candidates,
        len(donors) * config.shortlist_max_alternatives * evidence_strata,
    )
    naive_upper_bound = unique_upper_bound * len(config.transfer_budget_ladder)
    return {
        "donor_count": int(len(donors)),
        "receiver_candidate_count": receiver_candidates,
        "fast_candidate_count": None,
        "fast_candidate_count_reason": "not computed by the bounded dry plan; requires cheap-layer evaluation",
        "shortlist_upper_bound": int(len(donors) * config.shortlist_max_alternatives * evidence_strata),
        "expected_unique_full_verification_count": unique_upper_bound,
        "naive_pre_dedup_verification_count": naive_upper_bound,
        "duplicate_verification_savings_estimate": naive_upper_bound - unique_upper_bound,
        "count_semantics": {
            "donor_count": "EXACT",
            "receiver_candidate_count": "EXACT_SAME_REGION_SAME_PROFILE_SCOPE_BEFORE_EVIDENCE_FILTERS",
            "fast_candidate_count": "NOT_COMPUTED",
            "shortlist_upper_bound": "UPPER_BOUND",
            "expected_unique_full_verification_count": "UPPER_BOUND",
            "naive_pre_dedup_verification_count": "UPPER_BOUND",
            "duplicate_verification_savings_estimate": "UPPER_BOUND_DERIVED_DIFFERENCE",
        },
        "estimate_semantics": "explicit exact scope counts and conservative pre-evidence upper bounds",
        "full_scenario_evaluation_executed": False,
    }


def _distribution(values: list[float]) -> dict | None:
    import numpy as np

    data = np.asarray(values, dtype=float)
    if not len(data):
        return None
    return {
        "min": float(data.min()),
        "q1": float(np.quantile(data, 0.25)),
        "median": float(np.median(data)),
        "q3": float(np.quantile(data, 0.75)),
        "max": float(data.max()),
    }


def _composition(values: list[str]) -> dict[str, int]:
    return {value: values.count(value) for value in sorted(set(values))}


def _acceptance_summary(
    alternative_sets: list[dict],
    config,
    *,
    unique_full_verifications: int,
    verification_cache_reuses: int,
    runtime_seconds: float,
    peak_memory: float,
) -> dict:
    by_budget: dict[str, dict] = {}
    joint_strata = (
        "DIRECT_SUPPORTED|COMPLETE",
        "DIRECT_SUPPORTED|RANGE_LIMITED",
        "FALLBACK_LIMITED|COMPLETE",
        "FALLBACK_LIMITED|RANGE_LIMITED",
    )
    for budget in config.transfer_budget_ladder:
        rows = [item for item in alternative_sets if item["constraint_policy"]["max_transfer_fraction"] == budget]
        alternatives = [alternative for item in rows for alternative in item["alternatives"]]
        units_with_alternative = sum(bool(item["alternatives"]) for item in rows)
        primary_rows = [
            item for item in rows if item["donor_signal_ref"]["priority_support_class"] == "direct_supported"
        ]
        fallback_rows = [
            item for item in rows if item["donor_signal_ref"]["priority_support_class"] == "fallback_or_limited_history"
        ]
        primary_units_with_alternative = sum(
            any(
                alternative["forecast_support_tier"] == "DIRECT_SUPPORTED"
                and alternative["receiver_range_evidence"] == "COMPLETE"
                for alternative in item["alternatives"]
            )
            for item in primary_rows
        )
        fallback_units_with_alternative = sum(bool(item["alternatives"]) for item in fallback_rows)
        range_limited_units = sum(
            any(alternative["receiver_range_evidence"] == "RANGE_LIMITED" for alternative in item["alternatives"])
            for item in rows
        )
        range_limited_alternative_count = sum(
            alternative["receiver_range_evidence"] == "RANGE_LIMITED" for alternative in alternatives
        )
        abstained = [item for item in rows if item["abstention_status"]["abstained"]]
        reason_counts = {
            code: sum(code in item["abstention_status"]["codes"] for item in abstained)
            for code in sorted({code for item in abstained for code in item["abstention_status"]["codes"]})
        }
        phi_minimums = [
            float(item["donor_minimum_transfer_fraction"])
            for item in rows
            if item["donor_minimum_transfer_fraction"] is not None
        ]
        forecast_tiers = [item["forecast_support_tier"] for item in alternatives]
        range_tiers = [item["receiver_range_evidence"] for item in alternatives]
        joint_tiers = [f"{item['forecast_support_tier']}|{item['receiver_range_evidence']}" for item in alternatives]
        joint_composition = {stratum: joint_tiers.count(stratum) for stratum in joint_strata}
        zero_threshold_cells = dict.fromkeys(("NORMAL", "ELEVATED", "HIGH"), 0)
        zero_threshold_blocked = dict.fromkeys(("NORMAL", "ELEVATED", "HIGH"), 0)
        for item in rows:
            for rejected in item["abstention_status"]["rejected_receivers"]:
                for severity, count in rejected.get("zero_threshold_baseline_severities", {}).items():
                    zero_threshold_cells[severity] += int(count)
                    if rejected["code"] == "RECEIVER_BLOCKED" and count:
                        zero_threshold_blocked[severity] += 1
            for alternative in item["alternatives"]:
                for cell in alternative["baseline_receiver_state"]["cells"]:
                    if cell["threshold_status"] == "supported" and cell["threshold_value"] == 0:
                        severity = cell["severity"]
                        if severity in zero_threshold_cells:
                            zero_threshold_cells[severity] += 1
        full_verification_count = sum(item["alternatives_shortlisted"] for item in rows)
        verification_success_count = sum(len(item["alternatives"]) for item in rows)
        by_budget[format(budget, ".2f")] = {
            "units_evaluated": len(rows),
            "units_with_at_least_one_published_alternative": units_with_alternative,
            "at_least_one_alternative_rate": float(units_with_alternative / len(rows)) if rows else None,
            "published_alternative_count": len(alternatives),
            "primary_units_evaluated": len(primary_rows),
            "primary_units_with_at_least_one_direct_complete_alternative": primary_units_with_alternative,
            "primary_at_least_one_alternative_rate": (
                float(primary_units_with_alternative / len(primary_rows)) if primary_rows else None
            ),
            "fallback_units_evaluated": len(fallback_rows),
            "fallback_units_with_at_least_one_alternative": fallback_units_with_alternative,
            "fallback_at_least_one_alternative_rate": (
                float(fallback_units_with_alternative / len(fallback_rows)) if fallback_rows else None
            ),
            "units_with_range_limited_alternative": range_limited_units,
            "units_with_range_limited_alternative_rate": (float(range_limited_units / len(rows)) if rows else None),
            "range_limited_alternative_count": range_limited_alternative_count,
            "range_limited_alternative_share": (
                float(range_limited_alternative_count / len(alternatives)) if alternatives else None
            ),
            "unit_level_abstention_counts_by_reason": reason_counts,
            "unit_level_abstention_rates_by_reason": {
                code: float(count / len(rows)) if rows else None for code, count in reason_counts.items()
            },
            "minimum_phi_distribution": _distribution(phi_minimums),
            "phi_min_equal_one_share": (
                float(sum(value == 1.0 for value in phi_minimums) / len(phi_minimums)) if phi_minimums else None
            ),
            "donor_zero_threshold_binding_share": (
                float(sum(item["donor_zero_threshold_binding_present"] for item in rows) / len(rows)) if rows else None
            ),
            "receiver_zero_threshold_diagnostics": {
                "baseline_cell_counts": zero_threshold_cells,
                "receiver_blocked_candidate_counts": zero_threshold_blocked,
            },
            "transferred_expected_registrations_distribution": _distribution(
                [float(item["transferred_expected_registrations_total"]) for item in alternatives]
            ),
            "certify_up_steps_distribution": _distribution([float(item["certify_up_steps"]) for item in alternatives]),
            "sensitivity_range_result_composition": _composition(
                [item["sensitivity_range_result"] for item in alternatives]
            ),
            "forecast_support_tier_composition": _composition(forecast_tiers),
            "receiver_range_evidence_composition": _composition(range_tiers),
            "joint_evidence_stratum_composition": joint_composition,
            "receiver_worsening_count": sum(
                not alternative["receiver_no_worse_constraint_satisfied"] for alternative in alternatives
            ),
            "full_verification_count": full_verification_count,
            "full_verification_success_count": verification_success_count,
            "full_verification_success_rate": (
                float(verification_success_count / full_verification_count) if full_verification_count else None
            ),
            "verification_failure_count": sum(len(item["verification_failures"]) for item in rows),
            "alternatives_dropped_by_shortlist_bound": sum(
                len(item["alternatives_dropped_by_shortlist_bound"]) for item in rows
            ),
            "receiver_range_masking_present_count": sum(
                alternative["receiver_range_masking_present"] for alternative in alternatives
            ),
        }
    return {
        "acceptance_status": "EVIDENCE_GENERATED_REVIEW_PENDING",
        "real_data_acceptance_claimed": False,
        "primary_acceptance_stratum": ["DIRECT_SUPPORTED", "COMPLETE"],
        "verification_cache": {
            "unique_full_verifications": unique_full_verifications,
            "cache_reuses": verification_cache_reuses,
            "naive_pre_dedup_verification_count": unique_full_verifications + verification_cache_reuses,
        },
        "resource_use": {
            "runtime_seconds": runtime_seconds,
            "peak_memory_mib": peak_memory,
        },
        "by_policy_budget": by_budget,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "laptop", "overnight"), default="laptop")
    parser.add_argument("--run-id")
    parser.add_argument("--resume", metavar="RUN_ID")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--model-threads", type=int)
    parser.add_argument("--duckdb-memory-mb", type=int)
    args = parser.parse_args()

    resources = resource_config(
        args.profile,
        model_threads=args.model_threads,
        parallel_trials=1,
        process_concurrency=1,
        duckdb_memory_mb=args.duckdb_memory_mb,
    )
    apply_resource_environment(resources)

    import pandas as pd

    from hqai_ml.flow_forecast.config import load_flow_pressure_config, load_signal_prioritization_config
    from hqai_ml.flow_forecast.decision_alternatives import (
        ACCEPTED_SOURCE_RUN_IDS,
        FullVerificationCache,
        generate_decision_alternative_set,
        load_decision_alternatives_config,
    )
    from hqai_ml.flow_forecast.prioritization import (
        load_verified_pressure_signals,
        pressure_source_key,
        prioritization_key,
    )
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun, build_plan

    root = Path(__file__).resolve().parents[2]
    settings = IngestSettings()
    decision_path = settings.configs_dir / "decision_alternatives.yaml"
    pressure_path = settings.configs_dir / "flow_pressure.yaml"
    prioritization_path = settings.configs_dir / "signal_prioritization.yaml"
    config = load_decision_alternatives_config(decision_path)
    pressure_config = load_flow_pressure_config(pressure_path)
    prioritization_config = load_signal_prioritization_config(prioritization_path)

    entity, anomalies, pressure_lineage, pressure_summary = load_verified_pressure_signals(
        settings.artifacts_dir,
        config.source_pressure_run,
        prioritization_config,
    )
    pressure_run = ExperimentRun.read_only(settings.artifacts_dir, config.source_pressure_run)
    pressure_key = pressure_source_key(pressure_config.version)
    recorded_pressure = json.loads(pressure_run.checkpoint_path(pressure_key).read_text(encoding="utf-8"))
    pressure_checkpoint = pressure_run.reusable_checkpoint(pressure_key, parameters=recorded_pressure["parameters"])
    if pressure_checkpoint is None:
        raise ValueError("accepted pressure evaluation checkpoint is incomplete")
    pressure_artifact = settings.artifacts_dir / pressure_checkpoint["artifact"]["path"]
    daily = pd.read_parquet(pressure_artifact / "daily-pressure-signals.parquet")

    prioritization_run = ExperimentRun.read_only(settings.artifacts_dir, config.source_prioritization_run)
    priority = prioritization_run.manifest["hyperparameters"]["signal_prioritization"]
    priority_key = prioritization_key(priority["version"])
    recorded_priority = json.loads(prioritization_run.checkpoint_path(priority_key).read_text(encoding="utf-8"))
    priority_checkpoint = prioritization_run.reusable_checkpoint(
        priority_key, parameters=recorded_priority["parameters"]
    )
    if priority_checkpoint is None:
        raise ValueError("accepted prioritization evaluation checkpoint is incomplete")
    priority_artifact = settings.artifacts_dir / priority_checkpoint["artifact"]["path"]
    inbox = pd.read_parquet(priority_artifact / "views" / "top_priority_all.parquet")

    scenario_run = ExperimentRun.read_only(settings.artifacts_dir, config.source_scenario_run)
    if scenario_run.manifest["status"] != "completed":
        raise ValueError("accepted scenario source run is not completed")
    scenario_contract = scenario_run.manifest["hyperparameters"]["flow_scenario"]["scenario_contract_version"]
    if scenario_contract != config.scenario_contract_version:
        raise ValueError("accepted scenario run has an incompatible scenario contract")
    source_chain = scenario_run.manifest["hyperparameters"]["source_chain"]
    expected_runs = {
        "hierarchy": config.source_hierarchy_run,
        "pressure": config.source_pressure_run,
        "prioritization": config.source_prioritization_run,
    }
    for name, run_id in expected_runs.items():
        if source_chain[name]["source_run_id"] != run_id:
            raise ValueError(f"accepted scenario {name} lineage differs from the configured source")

    donors = _selected_donors(inbox, config)
    protocol = decision_protocol(config)
    lineage = {
        "hierarchy": pressure_summary["source_lineage"],
        "pressure": pressure_lineage,
        "prioritization": {
            "source_run_id": config.source_prioritization_run,
            "source_scientific_identity": prioritization_run.manifest["scientific_identity_sha256"],
            "evaluation_artifact_sha256": priority_checkpoint["artifact"]["sha256"],
        },
        "scenario": {
            "source_run_id": config.source_scenario_run,
            "source_scientific_identity": scenario_run.manifest["scientific_identity_sha256"],
        },
    }
    plan = build_plan(
        root=root,
        processed_dir=settings.processed_dir,
        configs_dir=settings.configs_dir,
        selected_models=["load_forecast"],
        resources=resources,
        temporal_protocols={"constrained_decision_alternatives": protocol},
        hyperparameters={
            "lightgbm": pressure_run.manifest["hyperparameters"]["lightgbm"],
            "decision_alternatives": config.model_dump(mode="json", exclude={"identity_sha256"}),
            "source_chain": lineage,
        },
        configuration_paths=[
            decision_path,
            pressure_path,
            prioritization_path,
            settings.configs_dir / "flow_scenario.yaml",
            settings.configs_dir / "models.yaml",
            settings.configs_dir / "ingest.yaml",
        ],
    )
    if plan["dataset"]["identity_sha256"] != pressure_lineage["source_dataset_identity"]:
        raise ValueError("current processed dataset differs from the accepted source dataset")
    plan_estimate = _verification_plan_estimate(donors, daily, config)
    if args.plan:
        print(
            store.canonical_json(
                {
                    "workflow": "constrained_decision_alternatives",
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "protocol": protocol,
                    "source_lineage": lineage,
                    "verification_estimate": plan_estimate,
                    "automatic_promotion": False,
                    "resources": plan["execution"]["resources"],
                }
            ),
            end="",
        )
        return 0
    _require_nonempty_donors(donors)
    _require_donor_daily_integrity(donors, daily)

    set_provenance = {
        "accepted_source_run_ids": ACCEPTED_SOURCE_RUN_IDS,
        "scenario_contract_version": config.scenario_contract_version,
        "scenario_scientific_identity": scenario_run.manifest["scientific_identity_sha256"],
        "decision_config_identity_sha256": config.identity_sha256,
        "code_identity_sha256": plan["code"]["source"]["sha256"],
        "execution_mode": "EVALUATION",
    }

    key = decision_evaluation_key(config.optimizer_contract_version)
    summary_key = CheckpointKey.model("load_forecast")
    parameters = {
        "decision_config_identity": config.identity_sha256,
        "source_pressure_artifact_sha256": pressure_checkpoint["artifact"]["sha256"],
        "source_prioritization_artifact_sha256": priority_checkpoint["artifact"]["sha256"],
        "source_scenario_scientific_identity": scenario_run.manifest["scientific_identity_sha256"],
    }
    parameters_by_key = {key.identifier: parameters}
    run = None
    active_key = None
    try:
        run = ExperimentRun.start(settings.artifacts_dir, plan, run_id=args.run_id, resume_run_id=args.resume)
        run_id = run.manifest["run_id"]
        checkpoint = run.reusable_checkpoint(key, parameters=parameters)
        reused = checkpoint is not None
        if checkpoint:
            artifact = settings.artifacts_dir / checkpoint["artifact"]["path"]
            analysis = json.loads((artifact / "decision-alternatives-summary.json").read_text(encoding="utf-8"))
            log("reused completed constrained decision alternatives checkpoint")
        else:
            run.start_checkpoint(key, parameters=parameters)
            active_key = key
            holder = {}

            def write_evaluation(directory: Path) -> None:
                alternative_sets = []
                verification_cache = FullVerificationCache()
                set_root = directory / "alternative-sets"
                set_root.mkdir()
                for donor in donors.itertuples(index=False):
                    for budget in config.transfer_budget_ladder:
                        log(f"evaluate donor {donor.hospital_id}/{donor.profile_id} at policy budget {budget:.2f}")
                        result = generate_decision_alternative_set(
                            baseline_daily=daily,
                            baseline_entity=entity,
                            donor_signal=pd.Series(donor._asdict()),
                            anomalies=anomalies,
                            pressure_config=pressure_config,
                            prioritization_config=prioritization_config,
                            config=config,
                            max_transfer_fraction=budget,
                            provenance=set_provenance,
                            verification_cache=verification_cache,
                        )
                        alternative_sets.append(result)
                        name = f"{result['canonical_unit_id']}-{budget:.2f}.json"
                        (set_root / name).write_text(store.canonical_json(result), encoding="utf-8")
                analysis_value = {
                    "schema_version": 1,
                    "run_id": run_id,
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "optimizer_contract_version": config.optimizer_contract_version,
                    "protocol": protocol,
                    "source_lineage": lineage,
                    "public_set_provenance": set_provenance,
                    "alternative_set_count": len(alternative_sets),
                    "acceptance": _acceptance_summary(
                        alternative_sets,
                        config,
                        unique_full_verifications=verification_cache.evaluation_count,
                        verification_cache_reuses=verification_cache.reuse_count,
                        runtime_seconds=time.perf_counter() - STARTED,
                        peak_memory=peak_memory_mib(),
                    ),
                    "automatic_promotion": False,
                    "model_registry_promotion": False,
                }
                (directory / "decision-alternatives-summary.json").write_text(
                    store.canonical_json(analysis_value), encoding="utf-8"
                )
                (directory / "config.json").write_text(
                    store.canonical_json(config.model_dump(mode="json")), encoding="utf-8"
                )
                holder["analysis"] = analysis_value

            artifact, artifact_manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "decision_alternatives" / run_id / "evaluation",
                "constrained-decision-alternatives",
                write_evaluation,
            )
            analysis = holder["analysis"]
            run.complete_checkpoint(
                key,
                parameters=parameters,
                metrics={
                    "alternative_set_count": analysis["alternative_set_count"],
                    "real_data_acceptance_claimed": False,
                    "automatic_promotion": False,
                },
                evaluation_status="completed",
                artifact_path=artifact,
                artifact_sha256=artifact_manifest["content_sha256"],
                version=config.optimizer_contract_version,
            )
            active_key = None

        summary = analysis | {
            "resource_use": {
                "profile": args.profile,
                "runtime_seconds": time.perf_counter() - STARTED,
                "peak_memory_mib": peak_memory_mib(),
                "reused_evaluation_checkpoint": reused,
            },
            "governance": {
                "human_review_required": True,
                "autonomous_action": False,
                "causal_effect_claimed": False,
                "capacity_checked": False,
                "serving_claim": False,
                "real_data_acceptance_claimed": False,
            },
        }
        summary_parameters = {
            "decision_alternatives_summary": True,
            "evaluation_checkpoint": key.identifier,
        }
        parameters_by_key[summary_key.identifier] = summary_parameters
        existing_summary = run.reusable_checkpoint(summary_key, parameters=summary_parameters)
        if existing_summary is None:
            run.start_checkpoint(summary_key, parameters=summary_parameters)
            active_key = summary_key

            def write_summary(directory: Path) -> None:
                (directory / "summary.json").write_text(store.canonical_json(summary), encoding="utf-8")

            summary_dir, summary_manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "decision_alternatives" / run_id / "summaries",
                "decision-alternatives-summary",
                write_summary,
            )
            run.complete_checkpoint(
                summary_key,
                parameters=summary_parameters,
                metrics={
                    "alternative_set_count": analysis["alternative_set_count"],
                    "human_review_required": True,
                    "real_data_acceptance_claimed": False,
                },
                evaluation_status="completed",
                artifact_path=summary_dir,
                artifact_sha256=summary_manifest["content_sha256"],
                version=config.optimizer_contract_version,
            )
            active_key = None
        else:
            summary_dir = settings.artifacts_dir / existing_summary["artifact"]["path"]
        if run.manifest["status"] != "completed":
            run.complete([key, summary_key], parameters_by_key=parameters_by_key)
        log(f"summary: {(summary_dir / 'summary.json').relative_to(root)}")
        log("completed; retrospective mathematical alternatives for human review only")
        return 0
    except KeyboardInterrupt:
        if run is not None:
            if active_key is not None:
                run.interrupt_checkpoint(active_key)
            run.pause()
        raise
    except BaseException as exc:
        if run is not None and run.manifest["status"] != "completed":
            if active_key is not None:
                run.fail_checkpoint(active_key, exc, root)
            run.fail(exc, root)
        raise
    finally:
        if run is not None:
            run.release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
