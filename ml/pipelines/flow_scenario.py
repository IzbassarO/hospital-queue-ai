#!/usr/bin/env python3
"""Run deterministic non-causal forecast stress tests against accepted flow evidence."""

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


def scenario_protocol(config, specs) -> dict:
    return {
        "execution_mode": "EVALUATION",
        "serving_claim": False,
        "target": config.target,
        "horizons": list(range(1, 15)),
        "scenario_contract_version": config.scenario_contract_version,
        "scenario_ids": [item.scenario_id for item in specs],
        "identity_reproduction_required_before_nonzero_scenario": True,
        "deterministic_synthetic_inputs": True,
        "counterfactual_validation_claimed": False,
        "queue_trajectory_output": False,
        "monte_carlo": False,
        "joint_predictive_distribution": False,
        "capacity_simulation": False,
        "causal_intervention_model": False,
        "cohort_hospitalizations_scenario_adjusted": False,
    }


def scenario_evaluation_key(version: str):
    from hqai_ml.registry.experiment import CheckpointKey

    return CheckpointKey(
        "load_forecast",
        candidate_id="forecast-stress-test",
        trial_id=version,
        fold_id="all-scenarios",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "laptop", "overnight"), default="laptop")
    parser.add_argument("--run-id")
    parser.add_argument("--resume", metavar="RUN_ID")
    parser.add_argument("--scenario-spec", type=Path, help="run one reviewed JSON ScenarioSpec instead of the suite")
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

    from hqai_ml.flow_forecast.config import (
        load_flow_pressure_config,
        load_signal_prioritization_config,
    )
    from hqai_ml.flow_forecast.prioritization import (
        load_verified_pressure_signals,
        pressure_source_key,
        prioritization_key,
    )
    from hqai_ml.flow_forecast.scenario import (
        BaselineProvenance,
        ScenarioClassification,
        ScenarioContractError,
        ScenarioScope,
        ScenarioSpec,
        assert_baseline_reproduction,
        canonical_spec_identity,
        evaluate_scenario,
        load_flow_scenario_config,
        load_scenario_spec,
        scenario_spec_scientific_payload,
        scenario_specs_from_config,
        scenario_summary,
    )
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun, build_plan
    from hqai_ml.registry.resources import seed_process

    root = Path(__file__).resolve().parents[2]
    settings = IngestSettings()
    scenario_path = settings.configs_dir / "flow_scenario.yaml"
    pressure_path = settings.configs_dir / "flow_pressure.yaml"
    prioritization_path = settings.configs_dir / "signal_prioritization.yaml"
    config = load_flow_scenario_config(scenario_path)
    pressure_config = load_flow_pressure_config(pressure_path)
    prioritization_config = load_signal_prioritization_config(prioritization_path)
    seed_process(pressure_config.seed)

    specs = [load_scenario_spec(args.scenario_spec)] if args.scenario_spec else scenario_specs_from_config(config)
    expected_provenance = BaselineProvenance(
        hierarchy_run_id=config.source_hierarchy_run,
        pressure_run_id=config.source_pressure_run,
        prioritization_run_id=config.source_prioritization_run,
    )
    for item in specs:
        if item.baseline_provenance != expected_provenance:
            raise ValueError(f"scenario {item.scenario_id!r} does not reference the configured accepted source chain")
        for lever in item.levers:
            expected_classification = config.classification_mapping.get(lever.lever_type)
            if expected_classification is None:
                raise ScenarioContractError(
                    "LEVER_UNSUPPORTED", f"lever {lever.lever_type!r} is not supported by scenario contract v1"
                )
            if lever.classification != expected_classification:
                raise ValueError(f"scenario {item.scenario_id!r} conflicts with the reviewed classification mapping")

    entity, anomalies, pressure_lineage, pressure_summary = load_verified_pressure_signals(
        settings.artifacts_dir, config.source_pressure_run, prioritization_config
    )
    if pressure_summary["source_lineage"]["source_run_id"] != config.source_hierarchy_run:
        raise ValueError("accepted pressure source does not reference the configured hierarchy run")
    pressure_run = ExperimentRun.read_only(settings.artifacts_dir, config.source_pressure_run)
    pressure_key = pressure_source_key(pressure_config.version)
    recorded_pressure = json.loads(pressure_run.checkpoint_path(pressure_key).read_text(encoding="utf-8"))
    pressure_checkpoint = pressure_run.reusable_checkpoint(pressure_key, parameters=recorded_pressure["parameters"])
    if pressure_checkpoint is None:
        raise ValueError("accepted pressure evaluation checkpoint is incomplete")
    pressure_artifact = settings.artifacts_dir / pressure_checkpoint["artifact"]["path"]
    daily = pd.read_parquet(pressure_artifact / "daily-pressure-signals.parquet")

    prioritization_run = ExperimentRun.read_only(settings.artifacts_dir, config.source_prioritization_run)
    if prioritization_run.manifest["status"] != "completed":
        raise ValueError("accepted prioritization run is not completed")
    source_pressure = prioritization_run.manifest["hyperparameters"]["source_pressure"]
    if source_pressure["source_run_id"] != config.source_pressure_run:
        raise ValueError("accepted prioritization source does not reference the configured pressure run")
    priority = prioritization_run.manifest["hyperparameters"]["signal_prioritization"]
    priority_key = prioritization_key(priority["version"])
    recorded_priority = json.loads(prioritization_run.checkpoint_path(priority_key).read_text(encoding="utf-8"))
    priority_checkpoint = prioritization_run.reusable_checkpoint(
        priority_key, parameters=recorded_priority["parameters"]
    )
    if priority_checkpoint is None:
        raise ValueError("accepted prioritization evaluation checkpoint is incomplete")
    priority_artifact = settings.artifacts_dir / priority_checkpoint["artifact"]["path"]
    accepted_inbox = pd.read_parquet(priority_artifact / "views" / "top_priority_all.parquet")
    accepted_unsupported = pd.read_parquet(priority_artifact / "views" / "unsupported_data_quality.parquet")
    accepted_low_volume = pd.read_parquet(priority_artifact / "views" / "zero_baseline_low_volume_attention.parquet")

    source_lineage = {
        "hierarchy": pressure_summary["source_lineage"],
        "pressure": pressure_lineage,
        "prioritization": {
            "source_run_id": config.source_prioritization_run,
            "source_scientific_identity": prioritization_run.manifest["scientific_identity_sha256"],
            "source_code_identity": prioritization_run.manifest["code"]["source"]["sha256"],
            "source_dataset_identity": prioritization_run.manifest["dataset"]["identity_sha256"],
            "source_configuration_identity": prioritization_run.manifest["configuration"]["sha256"],
            "evaluation_checkpoint_identity": priority_checkpoint["scientific_identity_sha256"],
            "evaluation_artifact_sha256": priority_checkpoint["artifact"]["sha256"],
        },
    }
    protocol = scenario_protocol(config, specs)
    plan = build_plan(
        root=root,
        processed_dir=settings.processed_dir,
        configs_dir=settings.configs_dir,
        selected_models=["load_forecast"],
        resources=resources,
        temporal_protocols={"forecast_stress_test": protocol},
        hyperparameters={
            "lightgbm": pressure_run.manifest["hyperparameters"]["lightgbm"],
            "flow_scenario": config.model_dump(mode="json", exclude={"identity_sha256", "standard_scenarios"}),
            # created_at is audit metadata; identical science must yield an identical scientific identity.
            "scenario_specs": [scenario_spec_scientific_payload(item) for item in specs],
            "source_chain": source_lineage,
        },
        configuration_paths=[
            scenario_path,
            pressure_path,
            prioritization_path,
            settings.configs_dir / "models.yaml",
            settings.configs_dir / "ingest.yaml",
        ],
    )
    if plan["dataset"]["identity_sha256"] != pressure_lineage["source_dataset_identity"]:
        raise ValueError("current processed dataset differs from the accepted scenario source dataset")
    if args.plan:
        print(
            store.canonical_json(
                {
                    "workflow": "forecast_stress_test",
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "scenario_contract_version": config.scenario_contract_version,
                    "scenario_specs": [item.model_dump(mode="json") for item in specs],
                    "source_lineage": source_lineage,
                    "protocol": protocol,
                    "identity_gate": "required_before_any_nonzero_scenario",
                    "automatic_promotion": False,
                    "resources": plan["execution"]["resources"],
                }
            ),
            end="",
        )
        return 0

    key = scenario_evaluation_key(config.scenario_contract_version)
    summary_key = CheckpointKey.model("load_forecast")
    parameters = {
        "scenario_config_identity": config.identity_sha256,
        "scenario_spec_identities": [canonical_spec_identity(item) for item in specs],
        "source_hierarchy_run": config.source_hierarchy_run,
        "source_pressure_run": config.source_pressure_run,
        "source_prioritization_run": config.source_prioritization_run,
        "source_pressure_artifact_sha256": pressure_checkpoint["artifact"]["sha256"],
        "source_prioritization_artifact_sha256": priority_checkpoint["artifact"]["sha256"],
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
            analysis = json.loads((artifact / "scenario-summary.json").read_text(encoding="utf-8"))
            validation = json.loads((artifact / "validation.json").read_text(encoding="utf-8"))
            log("reused completed forecast stress-test checkpoint")
        else:
            run.start_checkpoint(key, parameters=parameters)
            active_key = key
            holder = {}

            def write_evaluation(directory: Path) -> None:
                log("run mandatory accepted-baseline identity gate")
                identity_spec = ScenarioSpec(
                    scenario_id="mandatory-baseline-reproduction-gate",
                    scenario_version=config.scenario_contract_version,
                    scenario_type="identity",
                    classification=ScenarioClassification.SAFE_NON_CAUSAL_STRESS_TEST,
                    baseline_provenance=expected_provenance,
                    scope=ScenarioScope(),
                    parameters={},
                    created_at=specs[0].created_at,
                )
                identity = evaluate_scenario(daily, anomalies, pressure_config, prioritization_config, identity_spec)
                reproduction = assert_baseline_reproduction(
                    identity.daily_cells,
                    daily,
                    identity.entity_signals,
                    entity,
                    identity.inbox,
                    accepted_inbox,
                    identity.unsupported,
                    accepted_unsupported,
                    identity.low_volume_attention,
                    accepted_low_volume,
                )
                scenario_summaries = []
                scenario_validations = {"baseline_reproduction": reproduction, "scenarios": {}}
                scenario_root = directory / "scenarios"
                scenario_root.mkdir()
                for item in specs:
                    log(f"evaluate scenario {item.scenario_id}")
                    scenario_started = time.perf_counter()
                    result = evaluate_scenario(daily, anomalies, pressure_config, prioritization_config, item)
                    scenario_dir = scenario_root / item.scenario_id
                    scenario_dir.mkdir()
                    outputs = {
                        "scenario-cells.parquet": result.daily_cells,
                        "hierarchy-cells.parquet": result.hierarchy_cells,
                        "entity-signals.parquet": result.entity_signals,
                        "inbox.parquet": result.inbox,
                        "unsupported-data-quality.parquet": result.unsupported,
                        "zero-baseline-low-volume-attention.parquet": result.low_volume_attention,
                        "secondary-context-not-scenario-adjusted.parquet": result.secondary_context,
                        "daily-differences.parquet": result.daily_differences,
                        "entity-differences.parquet": result.entity_differences,
                    }
                    for name, frame in outputs.items():
                        frame.to_parquet(scenario_dir / name, index=False, compression="zstd")
                    summary = scenario_summary(result)
                    summary["resource_use"] = {
                        "runtime_seconds": time.perf_counter() - scenario_started,
                        "peak_memory_mib": peak_memory_mib(),
                    }
                    (scenario_dir / "summary.json").write_text(store.canonical_json(summary), encoding="utf-8")
                    (scenario_dir / "spec.json").write_text(
                        store.canonical_json(item.model_dump(mode="json")), encoding="utf-8"
                    )
                    scenario_summaries.append(summary)
                    scenario_validations["scenarios"][item.scenario_id] = result.validation
                anomalies.to_parquet(directory / "observed-anomaly-context.parquet", index=False, compression="zstd")
                analysis_value = {
                    "schema_version": 1,
                    "run_id": run_id,
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "scenario_contract_version": config.scenario_contract_version,
                    "source_lineage": source_lineage,
                    "protocol": protocol,
                    "scenarios": scenario_summaries,
                    "automatic_promotion": False,
                    "model_registry_promotion": False,
                }
                (directory / "scenario-summary.json").write_text(store.canonical_json(analysis_value), encoding="utf-8")
                (directory / "validation.json").write_text(store.canonical_json(scenario_validations), encoding="utf-8")
                (directory / "config.json").write_text(
                    store.canonical_json(config.model_dump(mode="json")), encoding="utf-8"
                )
                (directory / "manifest.json").write_text(
                    store.canonical_json(
                        {
                            "run_id": run_id,
                            "scenario_contract_identity": config.identity_sha256,
                            "source_lineage": source_lineage,
                            "scenario_spec_identities": parameters["scenario_spec_identities"],
                            "source_git": {
                                "commit": plan["code"]["git_commit"],
                                "dirty_worktree": plan["code"]["dirty_worktree"],
                            },
                            "source_code_identity": plan["code"]["source"]["sha256"],
                            "dataset_identity": plan["dataset"]["identity_sha256"],
                            "configuration_identity": plan["configuration"]["sha256"],
                            "execution_mode": "EVALUATION",
                            "serving_claim": False,
                        }
                    ),
                    encoding="utf-8",
                )
                holder["analysis"] = analysis_value
                holder["validation"] = scenario_validations

            artifact, artifact_manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "flow_scenario" / run_id / "evaluation",
                "forecast-stress-test",
                write_evaluation,
            )
            analysis = holder["analysis"]
            validation = holder["validation"]
            run.complete_checkpoint(
                key,
                parameters=parameters,
                metrics={
                    "scenario_count": len(specs),
                    "baseline_reproduction": validation["baseline_reproduction"]["status"],
                    "all_hierarchies_coherent": all(
                        item["hierarchy_coherence"]["within_tolerance"] for item in validation["scenarios"].values()
                    ),
                    "automatic_promotion": False,
                    "causal_effect_claimed": False,
                },
                evaluation_status="completed",
                artifact_path=artifact,
                artifact_sha256=artifact_manifest["content_sha256"],
                version=config.scenario_contract_version,
            )
            active_key = None

        summary = {
            **analysis,
            "validation": validation,
            "resource_use": {
                "profile": args.profile,
                "model_threads": resources.model_threads,
                "runtime_seconds": time.perf_counter() - STARTED,
                "peak_memory_mib": peak_memory_mib(),
                "reused_evaluation_checkpoint": reused,
            },
            "governance": {
                "human_review_required": True,
                "autonomous_action": False,
                "causal_claim": False,
                "capacity_checked": False,
                "automatic_model_promotion": False,
            },
        }
        summary_parameters = {
            "scenario_summary": True,
            "evaluation_checkpoint": key.identifier,
            "source_pressure_scientific_identity": pressure_lineage["source_scientific_identity"],
        }
        parameters_by_key[summary_key.identifier] = summary_parameters
        existing_summary = run.reusable_checkpoint(summary_key, parameters=summary_parameters)
        if existing_summary is None:
            run.start_checkpoint(summary_key, parameters=summary_parameters)
            active_key = summary_key

            def write_summary(directory: Path) -> None:
                (directory / "summary.json").write_text(store.canonical_json(summary), encoding="utf-8")
                (directory / "validation.json").write_text(store.canonical_json(validation), encoding="utf-8")

            summary_dir, summary_manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "flow_scenario" / run_id / "summaries",
                "scenario-summary",
                write_summary,
            )
            run.complete_checkpoint(
                summary_key,
                parameters=summary_parameters,
                metrics={
                    "scenario_count": len(specs),
                    "baseline_reproduction": validation["baseline_reproduction"]["status"],
                    "human_review_required": True,
                    "automatic_action": False,
                },
                evaluation_status="completed",
                artifact_path=summary_dir,
                artifact_sha256=summary_manifest["content_sha256"],
                version=config.scenario_contract_version,
            )
            active_key = None
        else:
            summary_dir = settings.artifacts_dir / existing_summary["artifact"]["path"]
        if run.manifest["status"] != "completed":
            run.complete([key, summary_key], parameters_by_key=parameters_by_key)
        log(f"summary: {(summary_dir / 'summary.json').relative_to(root)}")
        log("completed; offline forecast stress-test evidence for human review only")
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
