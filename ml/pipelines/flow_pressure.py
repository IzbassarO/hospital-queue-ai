#!/usr/bin/env python3
"""Prepare preventive historical-flow pressure warnings from accepted hierarchy artifacts."""

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


def pressure_protocol(config) -> dict:
    return {
        "origin_semantics": "last_observed_day",
        "horizons": list(range(1, config.horizon + 1)),
        "validation_origins": [str(origin) for origin in config.validation_origins],
        "final_test_origin": str(config.final_test_origin),
        "rolling_origin_only": True,
        "random_split": False,
        "fixed_rule_no_tuning": True,
        "final_test_used_for_rule_selection": False,
        "threshold_observations_at_or_before_origin": True,
        "threshold_semantics": config.threshold_semantics,
        "physical_capacity_used": False,
    }


def pressure_evaluation_key(version: str):
    from hqai_ml.registry.experiment import CheckpointKey

    return CheckpointKey(
        "load_forecast",
        candidate_id="preventive-flow-pressure",
        trial_id=version,
        fold_id="all-origins",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True)
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

    from hqai_ml.features.data import connect
    from hqai_ml.features.load import load_panels
    from hqai_ml.flow_forecast.config import load_flow_pressure_config
    from hqai_ml.flow_forecast.pressure import (
        DAILY_ALERT_UNIT,
        ENTITY_ORIGIN_ALERT_UNIT,
        aggregate_pressure_signals,
        derive_daily_pressure_signals,
        entity_origin_warning_metrics,
        historical_flow_thresholds,
        load_verified_hierarchy_forecasts,
        observed_flow_anomalies,
        representative_examples,
        retrospective_warning_metrics,
    )
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.models.config import load_model_config
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun, build_plan
    from hqai_ml.registry.resources import seed_process

    root = Path(__file__).resolve().parents[2]
    settings = IngestSettings()
    pressure_path = settings.configs_dir / "flow_pressure.yaml"
    config = load_flow_pressure_config(pressure_path)
    seed_process(config.seed)
    forecasts, source_lineage, source_summary = load_verified_hierarchy_forecasts(
        settings.artifacts_dir, args.source_run
    )
    source_run = ExperimentRun.read_only(settings.artifacts_dir, args.source_run)
    source_protocol = source_summary["protocol"]
    if [str(origin) for origin in config.validation_origins] != source_protocol["validation_origins"]:
        raise ValueError("pressure validation origins differ from the accepted hierarchy protocol")
    if str(config.final_test_origin) != source_protocol["final_test_origin"]:
        raise ValueError("pressure final origin differs from the accepted hierarchy protocol")
    if config.horizon != len(source_protocol["horizons"]):
        raise ValueError("pressure horizons differ from the accepted hierarchy protocol")

    protocol = pressure_protocol(config)
    plan = build_plan(
        root=root,
        processed_dir=settings.processed_dir,
        configs_dir=settings.configs_dir,
        selected_models=["load_forecast"],
        resources=resources,
        temporal_protocols={"preventive_flow_pressure": protocol},
        hyperparameters={
            "lightgbm": source_run.manifest["hyperparameters"]["lightgbm"],
            "flow_pressure": config.model_dump(mode="json", exclude={"identity_sha256"}),
            "source_hierarchy": source_lineage,
        },
        configuration_paths=[
            pressure_path,
            settings.configs_dir / "models.yaml",
            settings.configs_dir / "ingest.yaml",
        ],
    )
    if plan["dataset"]["identity_sha256"] != source_lineage["source_dataset_identity"]:
        raise ValueError("current processed dataset differs from the accepted hierarchy source dataset")
    if args.plan:
        print(
            store.canonical_json(
                {
                    "workflow": "preventive_flow_pressure",
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "source_lineage": source_lineage,
                    "protocol": protocol,
                    "threshold_contract": config.threshold.model_dump(mode="json"),
                    "anomaly_contract": config.anomaly.model_dump(mode="json"),
                    "threshold_semantics": config.threshold_semantics,
                    "compatible_future_threshold_semantics": config.compatible_future_threshold_semantics,
                    "forecast_models_retrained": False,
                    "physical_capacity_used": False,
                    "automatic_promotion": False,
                    "resources": plan["execution"]["resources"],
                }
            ),
            end="",
        )
        return 0

    key = pressure_evaluation_key(config.version)
    summary_key = CheckpointKey.model("load_forecast")
    parameters = {
        "source_run_id": args.source_run,
        "source_scientific_identity": source_lineage["source_scientific_identity"],
        "source_evaluation_artifact_sha256": source_lineage["evaluation_artifact_sha256"],
        "pressure_config_identity": config.identity_sha256,
        "threshold_semantics": config.threshold_semantics,
        "fixed_rule_no_tuning": True,
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
            daily = pd.read_parquet(artifact / "daily-pressure-signals.parquet")
            entity = pd.read_parquet(artifact / "entity-pressure-signals.parquet")
            anomalies = pd.read_parquet(artifact / "observed-flow-anomalies.parquet")
            analysis = json.loads((artifact / "retrospective-analysis.json").read_text(encoding="utf-8"))
            examples = json.loads((artifact / "representative-examples.json").read_text(encoding="utf-8"))
            log("reused completed flow-pressure checkpoint")
        else:
            run.start_checkpoint(key, parameters=parameters)
            active_key = key
            log("derive origin-legal historical flow thresholds and warnings")
            model_config = load_model_config(settings)
            holidays = set(model_config.load_forecast.holidays)
            con = connect(settings.processed_dir, resources)
            hospital, region = load_panels(con)
            con.close()
            origins = [*config.validation_origins, config.final_test_origin]
            targets = [config.primary_target, config.secondary_target]
            thresholds = historical_flow_thresholds(hospital, region, origins, targets, config, holidays)
            daily = derive_daily_pressure_signals(forecasts, thresholds, config)
            entity = aggregate_pressure_signals(daily, config)
            anomalies = observed_flow_anomalies(hospital, origins, config)
            identity_fields = {
                "signal_contract_version": config.version,
                "signal_scientific_identity": plan["scientific_identity_sha256"],
                "forecast_scientific_identity": source_lineage["source_scientific_identity"],
                "dataset_identity": source_lineage["source_dataset_identity"],
            }
            for name, value in identity_fields.items():
                daily[name] = value
                entity[name] = value
                anomalies[name] = value
            daily_metrics = retrospective_warning_metrics(daily)
            entity_metrics = entity_origin_warning_metrics(entity)
            examples = representative_examples(entity, anomalies)
            analysis = {
                "threshold_contract": config.threshold.model_dump(mode="json"),
                "severity_contract": {
                    "order": config.severity_order,
                    "WATCH": "available calibrated upper bound strictly exceeds threshold",
                    "ELEVATED": "central forecast strictly exceeds threshold",
                    "HIGH": "available calibrated lower bound strictly exceeds threshold",
                    "UNSUPPORTED": "origin-legal threshold evidence is insufficient",
                },
                "retrospective_evaluation": {
                    "daily_cell": {
                        "alert_unit": DAILY_ALERT_UNIT,
                        "metrics": daily_metrics,
                        "persistent_14_day_warning_maximum_alert_cells": 14,
                        "incident_or_episode_level": False,
                    },
                    "entity_origin": {
                        "alert_unit": ENTITY_ORIGIN_ALERT_UNIT,
                        "metrics": entity_metrics,
                        "incident_or_episode_level": False,
                    },
                },
                "rule_selection": {
                    "method": "single fixed pre-run contract; no candidate selection",
                    "validation_used_for_rule_selection": False,
                    "final_test_used_for_rule_selection": False,
                },
                "anomaly_contract": config.anomaly.model_dump(mode="json"),
                "physical_capacity_used": False,
                "automatic_action": False,
            }
            metadata = {
                "rows": {
                    "daily": len(daily),
                    "entity": len(entity),
                    "anomaly": len(anomalies),
                },
                "runtime_seconds": time.perf_counter() - STARTED,
                "peak_memory_mib": peak_memory_mib(),
                "model_threads": resources.model_threads,
                "forecast_models_retrained": False,
            }

            def write_evaluation(directory: Path) -> None:
                daily.to_parquet(directory / "daily-pressure-signals.parquet", index=False, compression="zstd")
                entity.to_parquet(directory / "entity-pressure-signals.parquet", index=False, compression="zstd")
                anomalies.to_parquet(directory / "observed-flow-anomalies.parquet", index=False, compression="zstd")
                (directory / "retrospective-analysis.json").write_text(store.canonical_json(analysis), encoding="utf-8")
                (directory / "representative-examples.json").write_text(
                    store.canonical_json(examples), encoding="utf-8"
                )
                (directory / "metadata.json").write_text(store.canonical_json(metadata), encoding="utf-8")

            artifact, artifact_manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "flow_pressure" / run_id / "evaluation",
                "preventive-flow-pressure",
                write_evaluation,
            )
            run.complete_checkpoint(
                key,
                parameters=parameters,
                metrics={
                    "daily_rows": len(daily),
                    "entity_rows": len(entity),
                    "anomaly_rows": len(anomalies),
                    "threshold_semantics": config.threshold_semantics,
                    "final_test_used_for_rule_selection": False,
                    "physical_capacity_used": False,
                },
                evaluation_status="completed",
                artifact_path=artifact,
                artifact_sha256=artifact_manifest["content_sha256"],
                version=config.version,
            )
            active_key = None

        summary = {
            "schema_version": 1,
            "run_id": run_id,
            "scientific_identity_sha256": plan["scientific_identity_sha256"],
            "source_lineage": source_lineage,
            "protocol": protocol,
            "signal_contract": {
                "version": config.version,
                "signal_names": ["flow_pressure", "high_load_warning", "unusual_flow_warning"],
                "threshold_semantics": config.threshold_semantics,
                "compatible_future_threshold_semantics": config.compatible_future_threshold_semantics,
                "physical_capacity_overload_claimed": False,
                "physical_capacity_probability_claimed": False,
                "signal_type_temporal_roles": {
                    "preventive_flow_pressure": "future_pressure_warning",
                    "observed_unusual_flow": "observed_anomaly",
                },
            },
            "alert_units": {
                "daily_cell": DAILY_ALERT_UNIT,
                "entity_origin": ENTITY_ORIGIN_ALERT_UNIT,
                "incident_or_episode_metrics_reported": False,
            },
            "analysis": analysis,
            "presentation_fields": [
                "signal_id",
                "signal_type",
                "alert_unit",
                "threshold_status",
                "threshold_fallback_level",
                "severity",
                "displayed_severity_basis",
                "severity_evidence_horizon",
                "severity_evidence_date",
                "entity_level",
                "hospital_id",
                "region_id",
                "profile_id",
                "forecast_origin",
                "first_crossing_date",
                "lead_time_days",
                "first_crossing_severity",
                "any_alert_7d",
                "any_alert_14d",
                "max_severity_7d",
                "max_severity_14d",
                "actual_event_within_7d",
                "actual_event_within_14d",
                "forecast_value",
                "threshold_value",
                "uncertainty_lower",
                "uncertainty_upper",
                "threshold_semantics",
                "forecast_source",
                "support_status",
                "fallback_status",
                "uncertainty_status",
                "reason_codes",
                "data_freshness",
                "signal_contract_version",
                "signal_scientific_identity",
                "forecast_scientific_identity",
                "dataset_identity",
            ],
            "representative_examples": examples,
            "governance": {
                "human_review_required": True,
                "autonomous_action": False,
                "patient_rerouting": False,
                "diagnosis_or_treatment_recommendation": False,
                "automatic_model_promotion": False,
            },
            "data_limitations": [
                "only 90 days of registration history; no annual-seasonality claim",
                "cohort_hospitalizations are Q1-referral-cohort events, not total admissions",
                "no physical bed capacity, occupied-bed, or free-bed data are available or inferred",
                "retrospective events are high-flow proxy exceedances, not operational incidents",
            ],
            "resource_use": {
                "profile": args.profile,
                "model_threads": resources.model_threads,
                "runtime_seconds": time.perf_counter() - STARTED,
                "peak_memory_mib": peak_memory_mib(),
                "reused_evaluation_checkpoint": reused,
            },
            "automatic_promotion": False,
        }
        summary_parameters = {
            "pressure_summary": True,
            "evaluation_checkpoint": key.identifier,
            "source_scientific_identity": source_lineage["source_scientific_identity"],
        }
        parameters_by_key[summary_key.identifier] = summary_parameters
        existing_summary = run.reusable_checkpoint(summary_key, parameters=summary_parameters)
        if existing_summary is None:
            run.start_checkpoint(summary_key, parameters=summary_parameters)
            active_key = summary_key

            def write_summary(directory: Path) -> None:
                (directory / "summary.json").write_text(store.canonical_json(summary), encoding="utf-8")

            summary_dir, summary_manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "flow_pressure" / run_id / "summaries",
                "pressure-summary",
                write_summary,
            )
            run.complete_checkpoint(
                summary_key,
                parameters=summary_parameters,
                metrics={
                    "threshold_semantics": config.threshold_semantics,
                    "validation_only_contract": True,
                    "automatic_promotion": False,
                    "autonomous_action": False,
                },
                evaluation_status="completed",
                artifact_path=summary_dir,
                artifact_sha256=summary_manifest["content_sha256"],
                version=config.version,
            )
            active_key = None
        else:
            summary_dir = settings.artifacts_dir / existing_summary["artifact"]["path"]
        if run.manifest["status"] != "completed":
            run.complete([key, summary_key], parameters_by_key=parameters_by_key)
        log(f"summary: {(summary_dir / 'summary.json').relative_to(root)}")
        log("completed; evidence for human review only")
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
