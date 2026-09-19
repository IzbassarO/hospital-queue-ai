#!/usr/bin/env python3
"""Evaluate central flow hierarchy and one fallback challenger without model retraining."""

from __future__ import annotations

import argparse
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


def hierarchy_protocol(config) -> dict:
    return {
        "origin_semantics": "last_observed_day",
        "horizons": list(range(1, config.horizon + 1)),
        "validation_origins": [str(origin) for origin in config.validation_origins],
        "final_test_origin": str(config.final_test_origin),
        "rolling_origin_only": True,
        "random_split": False,
        "validation_only_method_selection": True,
        "final_test_used_for_selection": False,
        "central_forecast_only": True,
        "probabilistic_reconciliation_applied": False,
    }


def evaluation_key(version: str):
    from hqai_ml.registry.experiment import CheckpointKey

    return CheckpointKey(
        "load_forecast",
        candidate_id="flow-hierarchy-central",
        trial_id=version,
        fold_id="all-origins",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--calibration-run", required=True)
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
    from hqai_ml.flow_forecast.calibration import load_verified_source_predictions
    from hqai_ml.flow_forecast.config import (
        load_flow_hierarchy_config,
        load_flow_quantile_config,
    )
    from hqai_ml.flow_forecast.hierarchy import (
        build_own_history_signals,
        evaluate_hierarchy,
        load_verified_calibration_intervals,
    )
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.models.config import load_model_config
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun, build_plan
    from hqai_ml.registry.resources import seed_process
    from pipelines.flow_quantile import build_quantile_plan, calibration_identity

    root = Path(__file__).resolve().parents[2]
    settings = IngestSettings()
    hierarchy_path = settings.configs_dir / "flow_hierarchy.yaml"
    quantile_path = settings.configs_dir / "flow_quantile.yaml"
    config = load_flow_hierarchy_config(hierarchy_path)
    quantile_config = load_flow_quantile_config(quantile_path)
    model_config = load_model_config(settings)
    model_config.lightgbm = {**model_config.lightgbm, "num_threads": resources.model_threads}
    seed_process(config.seed)
    phases = [(origin, "validation") for origin in config.validation_origins]
    phases.append((config.final_test_origin, "final_test"))
    cell_keys = ["phase", "origin", "target", "level", "series_id", "horizon", "target_date"]

    source_plan, source_protocol, residual_calibration_id = build_quantile_plan(
        root, settings, resources, quantile_config, model_config
    )
    if [str(origin) for origin in config.validation_origins] != source_protocol["validation_origins"]:
        raise ValueError("hierarchy validation origins differ from the accepted quantile protocol")
    if str(config.final_test_origin) != source_protocol["final_test_origin"]:
        raise ValueError("hierarchy final origin differs from the accepted quantile protocol")
    if config.horizon != len(source_protocol["horizons"]):
        raise ValueError("hierarchy horizons differ from the accepted quantile protocol")
    source_parameters = {
        "candidates": ["probabilistic_recent_seasonal_average", quantile_config.challenger.id],
        "quantiles": quantile_config.challenger.quantiles,
        "rounds": quantile_config.challenger.rounds,
        "search_configurations": 1,
        "calibration_identity": calibration_identity(quantile_config),
        "tuning": False,
    }
    raw, source_lineage = load_verified_source_predictions(
        settings.artifacts_dir,
        args.source_run,
        source_plan,
        phases,
        source_parameters,
        config.source_candidate,
        config.source_raw_variant,
    )
    central, central_lineage = load_verified_source_predictions(
        settings.artifacts_dir,
        args.source_run,
        source_plan,
        phases,
        source_parameters,
        config.source_candidate,
        config.source_central_variant,
    )
    if central_lineage["origin_artifacts"] != source_lineage["origin_artifacts"]:
        raise ValueError("raw and operational central variants do not share immutable source artifacts")
    raw = raw[
        cell_keys
        + [
            "org_code",
            "region_code",
            "profile_code",
            "y",
            "zero_rate",
            "density_band",
            "rmsse_scale",
            "historical_support_max",
            "supported",
            "p10",
            "p50",
            "p90",
            "candidate",
            "fallback_level",
            "prediction_source",
            "aggregation_method",
            "uncertainty_support",
            "calibration_id",
            "variant",
        ]
    ].copy()
    central = central[cell_keys + ["p50"]].copy()
    source_artifact_identity = hashlib.sha256(
        store.canonical_json(source_lineage["origin_artifacts"]).encode()
    ).hexdigest()
    calibration, calibration_lineage = load_verified_calibration_intervals(
        settings.artifacts_dir,
        args.calibration_run,
        args.source_run,
        source_lineage["source_scientific_identity"],
        source_artifact_identity,
        phases,
        config.calibration_method,
    )
    calibration = calibration[
        cell_keys
        + [
            "calibration_status",
            "calibration_version",
            "calibrated_interval_80_lower",
            "calibrated_interval_80_upper",
            "calibration_support_class",
        ]
    ].copy()

    protocol = hierarchy_protocol(config)
    plan = build_plan(
        root=root,
        processed_dir=settings.processed_dir,
        configs_dir=settings.configs_dir,
        selected_models=["load_forecast"],
        resources=resources,
        temporal_protocols={"flow_hierarchy_evidence": protocol},
        hyperparameters={
            "lightgbm": source_plan["hyperparameters"]["lightgbm"],
            "flow_hierarchy": config.model_dump(mode="json", exclude={"identity_sha256"}),
            "source_quantile": {
                "run_id": args.source_run,
                "scientific_identity": source_lineage["source_scientific_identity"],
                "artifact_identity": source_artifact_identity,
                "residual_baseline_calibration_identity": residual_calibration_id,
            },
            "source_calibration": {
                "run_id": args.calibration_run,
                "scientific_identity": calibration_lineage["calibration_scientific_identity"],
                "version": calibration_lineage["calibration_version"],
                "method": config.calibration_method,
            },
        },
        configuration_paths=[
            hierarchy_path,
            quantile_path,
            settings.configs_dir / "flow_calibration.yaml",
            settings.configs_dir / "models.yaml",
            settings.configs_dir / "ingest.yaml",
        ],
    )
    if args.plan:
        print(
            store.canonical_json(
                {
                    "workflow": "flow_hierarchy_evidence",
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "source_quantile_lineage": source_lineage,
                    "source_calibration_lineage": calibration_lineage,
                    "protocol": protocol,
                    "alternatives": config.alternatives,
                    "fallback_candidates": config.fallback.candidates,
                    "forecast_models_retrained": False,
                    "probabilistic_reconciliation_applied": False,
                    "automatic_promotion": False,
                    "resources": plan["execution"]["resources"],
                }
            ),
            end="",
        )
        return 0

    run = None
    key = evaluation_key(config.version)
    summary_key = CheckpointKey.model("load_forecast")
    parameters = {
        "source_artifact_identity": source_artifact_identity,
        "calibration_scientific_identity": calibration_lineage["calibration_scientific_identity"],
        "configuration_identity": config.identity_sha256,
        "alternatives": config.alternatives,
        "fallback_candidates": config.fallback.candidates,
    }
    parameters_by_key = {key.identifier: parameters}
    active_key = None
    try:
        run = ExperimentRun.start(settings.artifacts_dir, plan, run_id=args.run_id, resume_run_id=args.resume)
        run_id = run.manifest["run_id"]
        checkpoint = run.reusable_checkpoint(key, parameters=parameters)
        reused = checkpoint is not None
        if checkpoint:
            artifact = settings.artifacts_dir / checkpoint["artifact"]["path"]
            evaluation = pd.read_parquet(artifact / "selected-central-forecast.parquet")
            analysis = json.loads((artifact / "alternative-analysis.json").read_text(encoding="utf-8"))
            log("reused completed hierarchy evaluation checkpoint")
        else:
            run.start_checkpoint(key, parameters=parameters)
            active_key = key
            log("prepare immutable source rows; no forecast model retraining")
            raw = raw.rename(columns={"p10": "raw_p10", "p50": "raw_p50", "p90": "raw_p90"})
            source = raw.drop(columns=["variant"]).copy()
            source["source_raw_variant"] = config.source_raw_variant
            central_values = central.rename(columns={"p50": "source_central_value"})
            source = source.merge(central_values, on=cell_keys, how="left", validate="one_to_one")
            if source["source_central_value"].isna().any() or (source["source_central_value"] < 0).any():
                raise ValueError("accepted operational central p50 is missing or negative")

            level_local = calibration.rename(
                columns={
                    "calibrated_interval_80_lower": "level_local_interval_80_lower",
                    "calibrated_interval_80_upper": "level_local_interval_80_upper",
                }
            )
            source = source.merge(level_local, on=cell_keys, how="left", validate="one_to_one")
            if source["calibration_status"].isna().any():
                raise ValueError("accepted calibration rows do not cover every central source row")

            con = connect(settings.processed_dir, resources)
            hospital, _ = load_panels(con)
            con.close()
            signals = build_own_history_signals(
                hospital,
                [origin for origin, _ in phases],
                config.targets,
                quantile_config,
            )
            source = source.merge(
                signals,
                on=["origin", "target", "series_id", "horizon"],
                how="left",
                validate="many_to_one",
            )
            hospital_rows = source["level"] == "hospital"
            if source.loc[hospital_rows, "history_total"].isna().any():
                raise ValueError("own-history fallback evidence is missing for hospital rows")

            evaluation, analysis = evaluate_hierarchy(source, config)
            elapsed = time.perf_counter() - STARTED
            metadata = {
                "runtime_seconds": elapsed,
                "peak_memory_mib": peak_memory_mib(),
                "rows": len(evaluation),
                "model_threads": resources.model_threads,
                "forecast_models_retrained": False,
            }

            def write_evaluation(directory: Path) -> None:
                evaluation.to_parquet(
                    directory / "selected-central-forecast.parquet",
                    index=False,
                    compression="zstd",
                )
                (directory / "alternative-analysis.json").write_text(store.canonical_json(analysis), encoding="utf-8")
                (directory / "metadata.json").write_text(store.canonical_json(metadata), encoding="utf-8")

            artifact, manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "flow_hierarchy" / run_id / "evaluation",
                "central-hierarchy",
                write_evaluation,
            )
            run.complete_checkpoint(
                key,
                parameters=parameters,
                metrics={
                    "selected_fallback": analysis["fallback_selection"]["selected"],
                    "selected_hierarchy": analysis["hierarchy_selection"]["selected"],
                    "final_test_used_for_selection": False,
                    "rows": len(evaluation),
                },
                evaluation_status="completed",
                artifact_path=artifact,
                artifact_sha256=manifest["content_sha256"],
                version=config.version,
            )
            active_key = None

        summary = {
            "schema_version": 1,
            "run_id": run_id,
            "scientific_identity_sha256": plan["scientific_identity_sha256"],
            "source_quantile_lineage": source_lineage,
            "source_calibration_lineage": calibration_lineage,
            "protocol": protocol,
            "central_contract": {
                "source": "accepted repaired_nonnegative_monotone p50",
                "raw_p10_p50_p90_preserved": True,
                "reconciled_outputs_separately_labelled": True,
                "probabilistic_reconciliation_applied": False,
                "national_central_may_be_exact_region_sum": True,
                "national_quantiles_created": False,
            },
            "analysis": analysis,
            "presentation_fields": [
                "forecast_value",
                "forecast_source",
                "hierarchy_status",
                "support_status",
                "fallback_status",
                "uncertainty_status",
                "calibration_version",
            ],
            "data_limitations": [
                "only 90 days of registration history; no annual-seasonality claim",
                "cohort_hospitalizations are Q1-referral-cohort events, not total admissions",
                "no bed occupancy, free-bed, or physical-capacity inference",
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
            "hierarchy_summary": True,
            "evaluation_checkpoint": key.identifier,
            "source_artifact_identity": source_artifact_identity,
        }
        parameters_by_key[summary_key.identifier] = summary_parameters
        existing_summary = run.reusable_checkpoint(summary_key, parameters=summary_parameters)
        if existing_summary is None:
            run.start_checkpoint(summary_key, parameters=summary_parameters)
            active_key = summary_key

            def write_summary(directory: Path) -> None:
                (directory / "summary.json").write_text(store.canonical_json(summary), encoding="utf-8")

            summary_dir, summary_manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "flow_hierarchy" / run_id / "summaries",
                "hierarchy-summary",
                write_summary,
            )
            run.complete_checkpoint(
                summary_key,
                parameters=summary_parameters,
                metrics={
                    "selected_fallback": analysis["fallback_selection"]["selected"],
                    "selected_hierarchy": analysis["hierarchy_selection"]["selected"],
                    "validation_only_selection": True,
                    "automatic_promotion": False,
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
        log("completed; no model promoted and no probabilistic reconciliation claimed")
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
