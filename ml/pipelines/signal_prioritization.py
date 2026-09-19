#!/usr/bin/env python3
"""Prepare a deterministic, explainable entity/origin Signals Inbox."""

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


def prioritization_protocol(config, source_summary: dict) -> dict:
    return {
        "canonical_signal_unit": config.source_alert_unit,
        "daily_cells_loaded": False,
        "primary_target": config.primary_target,
        "secondary_target": config.secondary_target,
        "secondary_target_semantics": "Q1_referral_cohort_evidence_not_total_admissions",
        "materiality_floor_expected_count": config.materiality_floor_expected_count,
        "materiality_rule_tuned_from_outcomes": False,
        "ranking_method": "fixed_lexicographic_no_learned_or_weighted_score",
        "ranking_order": config.ranking_order,
        "validation_independent_rules": True,
        "final_test_used_for_rule_selection": False,
        "source_temporal_protocol": source_summary["protocol"],
    }


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

    from hqai_ml.flow_forecast.config import load_signal_prioritization_config
    from hqai_ml.flow_forecast.prioritization import (
        demo_artifacts,
        inbox_views,
        load_verified_pressure_signals,
        materiality_diagnostics,
        observed_anomaly_view,
        prepare_inbox,
        prioritization_key,
        regional_rollup,
    )
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun, build_plan
    from hqai_ml.registry.resources import seed_process

    root = Path(__file__).resolve().parents[2]
    settings = IngestSettings()
    config_path = settings.configs_dir / "signal_prioritization.yaml"
    config = load_signal_prioritization_config(config_path)
    seed_process(config.seed)
    entity, anomalies, source_lineage, source_summary = load_verified_pressure_signals(
        settings.artifacts_dir, args.source_run, config
    )
    source_run = ExperimentRun.read_only(settings.artifacts_dir, args.source_run)
    protocol = prioritization_protocol(config, source_summary)
    plan = build_plan(
        root=root,
        processed_dir=settings.processed_dir,
        configs_dir=settings.configs_dir,
        selected_models=["load_forecast"],
        resources=resources,
        temporal_protocols={"signal_prioritization": protocol},
        hyperparameters={
            "lightgbm": source_run.manifest["hyperparameters"]["lightgbm"],
            "signal_prioritization": config.model_dump(mode="json", exclude={"identity_sha256"}),
            "source_pressure": source_lineage,
        },
        configuration_paths=[
            config_path,
            settings.configs_dir / "models.yaml",
            settings.configs_dir / "ingest.yaml",
        ],
    )
    if plan["dataset"]["identity_sha256"] != source_lineage["source_dataset_identity"]:
        raise ValueError("current processed dataset differs from the accepted pressure source dataset")
    if args.plan:
        print(
            store.canonical_json(
                {
                    "workflow": "signal_prioritization",
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "source_lineage": source_lineage,
                    "protocol": protocol,
                    "ranking_contract": {
                        "method": protocol["ranking_method"],
                        "order": config.ranking_order,
                        "unsupported_queue_separate": True,
                        "zero_baseline_low_volume_attention_separate": True,
                        "materiality_floor_expected_count": config.materiality_floor_expected_count,
                        "observed_anomaly_changes_pressure_severity": False,
                    },
                    "source_entity_rows": len(entity),
                    "source_anomaly_rows": len(anomalies),
                    "automatic_promotion": False,
                    "resources": plan["execution"]["resources"],
                }
            ),
            end="",
        )
        return 0

    key = prioritization_key(config.version)
    summary_key = CheckpointKey.model("load_forecast")
    parameters = {
        "source_run_id": args.source_run,
        "source_scientific_identity": source_lineage["source_scientific_identity"],
        "source_evaluation_artifact_sha256": source_lineage["evaluation_artifact_sha256"],
        "prioritization_config_identity": config.identity_sha256,
        "canonical_signal_unit": config.source_alert_unit,
        "materiality_floor_expected_count": config.materiality_floor_expected_count,
        "ranking_order": config.ranking_order,
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
            view_names = [
                "top_priority_all",
                "high_only",
                "watchlist_7d",
                "watchlist_14d",
                "fallback_attention",
                "unsupported_data_quality",
                "zero_baseline_low_volume_attention",
                "observed_anomalies",
            ]
            views = {name: pd.read_parquet(artifact / "views" / f"{name}.parquet") for name in view_names}
            secondary = pd.read_parquet(artifact / "secondary-research-evidence.parquet")
            regional = pd.read_parquet(artifact / "regional-summary.parquet")
            demos = json.loads((artifact / "demo-artifacts.json").read_text(encoding="utf-8"))
            analysis = json.loads((artifact / "analysis.json").read_text(encoding="utf-8"))
            log("reused completed Signals Inbox checkpoint")
        else:
            run.start_checkpoint(key, parameters=parameters)
            active_key = key
            log("prepare deterministic entity/origin ranking and explanations")
            ranked, unsupported, low_volume, secondary = prepare_inbox(entity, anomalies, config)
            observed = observed_anomaly_view(anomalies, entity)
            views = inbox_views(ranked, unsupported, low_volume, observed)
            regional = regional_rollup(entity, config)
            demos = demo_artifacts(views, regional, config)
            materiality = materiality_diagnostics(ranked, low_volume, config)
            identity_fields = {
                "prioritization_contract_version": config.version,
                "prioritization_scientific_identity": plan["scientific_identity_sha256"],
                "source_pressure_scientific_identity": source_lineage["source_scientific_identity"],
                "dataset_identity": source_lineage["source_dataset_identity"],
            }
            for frame in [*views.values(), secondary, regional]:
                for name, value in identity_fields.items():
                    frame[name] = value
            analysis = {
                "ranking_contract": {
                    "method": "fixed_lexicographic_no_learned_or_weighted_score",
                    "partition": ["phase", "origin", "target"],
                    "order": config.ranking_order,
                    "ratio_definition": "forecast_value / threshold_value only when threshold_value > 0",
                    "unsupported_queue_separate": True,
                    "zero_baseline_low_volume_excluded": True,
                },
                "materiality_contract": {
                    "status": "fixed_product_triage_not_model_calibration",
                    "floor_expected_count": config.materiality_floor_expected_count,
                    "condition": "supported threshold == 0 and central forecast < floor",
                    "source_severity_changed": False,
                    "source_pressure_artifacts_changed": False,
                    "source_retrospective_metrics_recomputed_or_changed": False,
                    **materiality,
                },
                "consolidation_contract": {
                    "unit": config.source_alert_unit,
                    "one_row_per_hospital_profile_target_origin": True,
                    "daily_cells_loaded": False,
                    "first_crossing_preserved": True,
                    "maximum_severity_evidence_preserved": True,
                },
                "explanation_contract": {
                    "deterministic_templates": True,
                    "causal_claims": False,
                    "fields": ["headline", "concise_reason", "reason_codes", "evidence_facts"],
                },
                "anomaly_contract": {
                    "separate_signal_type": True,
                    "context_field": "observed_anomaly_present",
                    "changes_pressure_severity": False,
                },
                "view_counts": {name: len(frame) for name, frame in views.items()},
                "secondary_research_rows": len(secondary),
                "regional_rows": len(regional),
            }

            def write_evaluation(directory: Path) -> None:
                view_dir = directory / "views"
                view_dir.mkdir()
                for name, frame in views.items():
                    frame.to_parquet(view_dir / f"{name}.parquet", index=False, compression="zstd")
                secondary.to_parquet(directory / "secondary-research-evidence.parquet", index=False, compression="zstd")
                regional.to_parquet(directory / "regional-summary.parquet", index=False, compression="zstd")
                (directory / "demo-artifacts.json").write_text(store.canonical_json(demos), encoding="utf-8")
                (directory / "analysis.json").write_text(store.canonical_json(analysis), encoding="utf-8")
                (directory / "metadata.json").write_text(
                    store.canonical_json(
                        {
                            "source_entity_rows": len(entity),
                            "source_anomaly_rows": len(anomalies),
                            "runtime_seconds": time.perf_counter() - STARTED,
                            "peak_memory_mib": peak_memory_mib(),
                            "model_threads": resources.model_threads,
                            "forecast_models_retrained": False,
                        }
                    ),
                    encoding="utf-8",
                )

            artifact, artifact_manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "flow_prioritization" / run_id / "evaluation",
                "signals-inbox",
                write_evaluation,
            )
            run.complete_checkpoint(
                key,
                parameters=parameters,
                metrics={
                    "primary_inbox_rows": len(views["top_priority_all"]),
                    "unsupported_data_quality_rows": len(views["unsupported_data_quality"]),
                    "observed_anomaly_rows": len(views["observed_anomalies"]),
                    "zero_baseline_low_volume_attention_rows": len(views["zero_baseline_low_volume_attention"]),
                    "canonical_signal_unit": config.source_alert_unit,
                    "source_severity_changed": False,
                    "automatic_action": False,
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
            "analysis": analysis,
            "inbox_views": {name: {"rows": len(frame)} for name, frame in views.items()},
            "presentation_fields": [
                "inbox_rank",
                "source_severity",
                "severity",
                "operational_priority_status",
                "materiality_status",
                "materiality_floor_expected_count",
                "signal_type",
                "hospital_id",
                "region_id",
                "profile_id",
                "forecast_origin",
                "first_crossing_date",
                "lead_time_days",
                "max_severity_7d",
                "max_severity_14d",
                "severity_evidence_horizon",
                "severity_evidence_date",
                "forecast_value",
                "threshold_value",
                "uncertainty_lower",
                "uncertainty_upper",
                "forecast_source",
                "support_status",
                "fallback_status",
                "uncertainty_status",
                "threshold_status",
                "data_freshness",
                "observed_anomaly_present",
                "headline",
                "concise_reason",
                "reason_codes",
                "evidence_facts",
            ],
            "regional_rollup": {
                "rows": len(regional),
                "new_risk_model": False,
                "target": config.primary_target,
            },
            "demo_artifacts": demos,
            "governance": {
                "human_review_required": True,
                "autonomous_action": False,
                "patient_rerouting": False,
                "diagnosis_or_treatment_recommendation": False,
                "automatic_model_promotion": False,
            },
            "data_limitations": [
                "only 90 days of registration history; no annual-seasonality claim",
                "cohort_hospitalizations are secondary Q1-referral-cohort evidence, not total admissions",
                "pressure warnings are historical-flow proxy states, not physical-capacity overload",
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
            "signals_inbox_summary": True,
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
                settings.artifacts_dir / "flow_prioritization" / run_id / "summaries",
                "signals-inbox-summary",
                write_summary,
            )
            run.complete_checkpoint(
                summary_key,
                parameters=summary_parameters,
                metrics={
                    "canonical_signal_unit": config.source_alert_unit,
                    "primary_target": config.primary_target,
                    "human_review_required": True,
                    "automatic_action": False,
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
        log("completed; deterministic Signals Inbox for human review only")
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
