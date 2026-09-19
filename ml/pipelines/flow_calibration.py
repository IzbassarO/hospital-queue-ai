#!/usr/bin/env python3
"""Calibrate saved raw flow-quantile intervals without retraining forecast models."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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


def calibration_origin_key(origin: dt.date, phase: str, version: str):
    from hqai_ml.registry.experiment import CheckpointKey

    return CheckpointKey(
        "load_forecast",
        candidate_id="flow-temporal-calibration",
        trial_id=version,
        fold_id=phase,
        forecast_origin=origin.isoformat(),
    )


def calibration_protocol(config) -> dict:
    return {
        "origin_semantics": "last_observed_day",
        "validation_origins": [str(origin) for origin in config.validation_origins],
        "final_test_origin": str(config.final_test_origin),
        "random_split": False,
        "source_variant": "raw",
        "final_test_used_for_calibration_parameter_selection": False,
        "calibration_outcomes_must_be_observable_by_origin": True,
        "national_proxy_calibration_claimed": False,
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

    from hqai_ml.flow_forecast.calibration import (
        calibrate_origin,
        calibration_version,
        load_verified_source_predictions,
        summarize_calibration,
    )
    from hqai_ml.flow_forecast.config import (
        load_flow_quantile_config,
        load_temporal_calibration_config,
    )
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.models.config import load_model_config
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun, build_plan
    from hqai_ml.registry.resources import seed_process
    from pipelines.flow_quantile import build_quantile_plan, calibration_identity

    root = Path(__file__).resolve().parents[2]
    settings = IngestSettings()
    calibration_path = settings.configs_dir / "flow_calibration.yaml"
    quantile_path = settings.configs_dir / "flow_quantile.yaml"
    config = load_temporal_calibration_config(calibration_path)
    quantile_config = load_flow_quantile_config(quantile_path)
    model_config = load_model_config(settings)
    model_config.lightgbm = {**model_config.lightgbm, "num_threads": resources.model_threads}
    seed_process(config.seed)
    version = calibration_version(config)
    phases = [(origin, "validation") for origin in config.validation_origins]
    phases.append((config.final_test_origin, "final_test"))

    source_plan, source_protocol, residual_calibration_id = build_quantile_plan(
        root, settings, resources, quantile_config, model_config
    )
    if [str(origin) for origin in config.validation_origins] != source_protocol["validation_origins"]:
        raise ValueError("calibration validation origins differ from the source quantile protocol")
    if str(config.final_test_origin) != source_protocol["final_test_origin"]:
        raise ValueError("calibration final origin differs from the source quantile protocol")
    source_parameters = {
        "candidates": ["probabilistic_recent_seasonal_average", quantile_config.challenger.id],
        "quantiles": quantile_config.challenger.quantiles,
        "rounds": quantile_config.challenger.rounds,
        "search_configurations": 1,
        "calibration_identity": calibration_identity(quantile_config),
        "tuning": False,
    }
    source, source_lineage = load_verified_source_predictions(
        settings.artifacts_dir,
        args.source_run,
        source_plan,
        phases,
        source_parameters,
        config.candidate,
    )
    source_artifact_identity = hashlib.sha256(
        store.canonical_json(source_lineage["origin_artifacts"]).encode()
    ).hexdigest()
    protocol = calibration_protocol(config)
    plan = build_plan(
        root=root,
        processed_dir=settings.processed_dir,
        configs_dir=settings.configs_dir,
        selected_models=["load_forecast"],
        resources=resources,
        temporal_protocols={"flow_temporal_calibration": protocol},
        hyperparameters={
            "lightgbm": source_plan["hyperparameters"]["lightgbm"],
            "calibration_version": version,
            "calibration": config.model_dump(mode="json", exclude={"identity_sha256"}),
            "source_run": {
                "run_id": args.source_run,
                "scientific_identity": source_lineage["source_scientific_identity"],
                "source_code_identity": source_lineage["source_code_identity"],
                "current_code_identity": source_lineage["current_code_identity"],
                "compatibility": source_lineage["compatibility"],
                "artifact_identity": source_artifact_identity,
                "residual_baseline_calibration_identity": residual_calibration_id,
            },
        },
        configuration_paths=[
            calibration_path,
            quantile_path,
            settings.configs_dir / "models.yaml",
            settings.configs_dir / "ingest.yaml",
        ],
    )
    if args.plan:
        print(
            store.canonical_json(
                {
                    "workflow": "flow_temporal_calibration",
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "calibration_version": version,
                    "source_lineage": source_lineage,
                    "source_artifact_identity": source_artifact_identity,
                    "protocol": protocol,
                    "resources": plan["execution"]["resources"],
                    "origin_checkpoints": [
                        calibration_origin_key(origin, phase, version).to_dict() for origin, phase in phases
                    ],
                    "forecast_models_retrained": False,
                    "automatic_promotion": False,
                }
            ),
            end="",
        )
        return 0

    run = None
    origin_keys = []
    parameters_by_key = {}
    try:
        run = ExperimentRun.start(settings.artifacts_dir, plan, run_id=args.run_id, resume_run_id=args.resume)
        run_id = run.manifest["run_id"]
        log(f"run {run_id}; source={args.source_run}; no forecast retraining")
        frames = []
        audits = []
        origin_resources = []
        reused = 0
        parameters = {
            "calibration_version": version,
            "source_artifact_identity": source_artifact_identity,
            "methods": config.methods,
            "source_variant": config.source_variant,
        }
        holidays = set(model_config.load_forecast.holidays)
        for origin, phase in phases:
            key = calibration_origin_key(origin, phase, version)
            origin_keys.append(key)
            parameters_by_key[key.identifier] = parameters
            checkpoint = run.reusable_checkpoint(key, parameters=parameters)
            if checkpoint:
                artifact = settings.artifacts_dir / checkpoint["artifact"]["path"]
                frames.append(pd.read_parquet(artifact / "calibrated-evaluation.parquet"))
                metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
                audits.append(metadata["temporal_audit"])
                origin_resources.append(metadata["resources"])
                reused += 1
                log(f"reuse {phase} origin {origin} checkpoint")
                continue
            run.start_checkpoint(key, parameters=parameters)
            origin_started = time.perf_counter()
            try:
                log(f"calibrate {phase} origin {origin}")
                frame, audit = calibrate_origin(source, origin, config, holidays)
                elapsed = time.perf_counter() - origin_started
                metadata = {
                    "temporal_audit": audit,
                    "resources": {
                        "origin": str(origin),
                        "phase": phase,
                        "runtime_seconds": elapsed,
                        "peak_memory_mib": peak_memory_mib(),
                        "rows": len(frame),
                    },
                }

                def write_origin(
                    directory: Path,
                    result=frame,
                    result_metadata=metadata,
                ) -> None:
                    result.to_parquet(
                        directory / "calibrated-evaluation.parquet",
                        index=False,
                        compression="zstd",
                    )
                    (directory / "metadata.json").write_text(store.canonical_json(result_metadata), encoding="utf-8")

                artifact, manifest = store.publish_artifact_directory(
                    settings.artifacts_dir / "flow_calibration" / run_id / "origins",
                    f"{phase}-{origin}",
                    write_origin,
                )
                run.complete_checkpoint(
                    key,
                    parameters=parameters,
                    metrics={
                        "runtime_seconds": elapsed,
                        "rows": len(frame),
                        "calibration_pool_rows": audit["calibration_pool_rows"],
                        "final_test_rows_in_calibration_pool": audit["final_test_rows_in_calibration_pool"],
                    },
                    evaluation_status="completed",
                    artifact_path=artifact,
                    artifact_sha256=manifest["content_sha256"],
                    version=f"{version}-{phase}-{origin}",
                )
                frames.append(frame)
                audits.append(audit)
                origin_resources.append(metadata["resources"])
            except KeyboardInterrupt:
                run.interrupt_checkpoint(key)
                raise
            except BaseException as exc:
                run.fail_checkpoint(key, exc, root)
                raise

        evaluation = pd.concat(frames, ignore_index=True)
        metrics = summarize_calibration(evaluation, config)
        summary = {
            "schema_version": 1,
            "run_id": run_id,
            "scientific_identity_sha256": plan["scientific_identity_sha256"],
            "calibration_version": version,
            "calibration_identity_sha256": config.identity_sha256,
            "model_version_independent": True,
            "source_lineage": source_lineage,
            "source_artifact_identity": source_artifact_identity,
            "protocol": protocol,
            "method_contract": {
                "primary": "conformal_interval_expansion",
                "baseline": "median_absolute_residual_baseline",
                "raw_predictions_preserved": True,
                "calibrated_bounds_are_not_relabeled_quantiles": True,
                "lower_bound_transform": "max(0, unbounded calibrated lower)",
                "upper_bound_ordering_transform": "max(calibrated lower, unbounded calibrated upper)",
                "fallback_ladder": config.fallback_ladder,
                "minimum_scores": config.minimum_scores,
                "minimum_unique_target_dates": config.minimum_unique_target_dates,
            },
            "support_classes": {
                "direct_quantile_ml": "separately calibrated",
                "region_profile_share_fallback": "separately calibrated",
                "own_history_no_uncertainty": "unsupported; no interval fabricated",
                "national_proxy": "excluded from national calibration claims",
            },
            "temporal_audits": audits,
            "metrics": metrics,
            "resource_use": {
                "profile": args.profile,
                "origins": origin_resources,
                "runtime_seconds": time.perf_counter() - STARTED,
                "peak_memory_mib": peak_memory_mib(),
                "reused_checkpoints": reused,
            },
            "forecast_models_retrained": False,
            "automatic_promotion": False,
        }
        summary_key = CheckpointKey.model("load_forecast")
        summary_parameters = {
            "temporal_calibration_summary": True,
            "origin_checkpoint_ids": [key.identifier for key in origin_keys],
            "source_artifact_identity": source_artifact_identity,
        }
        parameters_by_key[summary_key.identifier] = summary_parameters
        existing_summary = run.reusable_checkpoint(summary_key, parameters=summary_parameters)
        if existing_summary is None:
            run.start_checkpoint(summary_key, parameters=summary_parameters)

            def write_summary(directory: Path) -> None:
                (directory / "summary.json").write_text(store.canonical_json(summary), encoding="utf-8")

            summary_dir, manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "flow_calibration" / run_id / "summaries",
                "temporal-calibration-summary",
                write_summary,
            )
            run.complete_checkpoint(
                summary_key,
                parameters=summary_parameters,
                metrics={
                    "nominal_coverage": config.nominal_coverage,
                    "acceptance_decision_made": False,
                    "automatic_promotion": False,
                    "reused_checkpoints": reused,
                },
                evaluation_status="completed",
                artifact_path=summary_dir,
                artifact_sha256=manifest["content_sha256"],
                version=version,
            )
        else:
            summary_dir = settings.artifacts_dir / existing_summary["artifact"]["path"]
        required = [*origin_keys, summary_key]
        if run.manifest["status"] != "completed":
            run.complete(required, parameters_by_key=parameters_by_key)
        log(f"summary: {(summary_dir / 'summary.json').relative_to(root)}")
        log(f"completed; reused checkpoints={reused}; no model promoted")
        return 0
    except KeyboardInterrupt:
        if run is not None:
            run.pause()
        raise
    except BaseException as exc:
        if run is not None and run.manifest["status"] != "completed":
            run.fail(exc, root)
        raise
    finally:
        if run is not None:
            run.release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
