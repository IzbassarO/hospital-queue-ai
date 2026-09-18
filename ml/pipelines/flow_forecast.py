#!/usr/bin/env python3
"""Build non-promoting evidence for 1..14-day referral-flow count forecasts."""

from __future__ import annotations

import argparse
import datetime as dt
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


def origin_key(origin, phase):
    from hqai_ml.registry.experiment import CheckpointKey

    return CheckpointKey(
        "load_forecast",
        candidate_id="flow-evidence",
        trial_id="fixed",
        fold_id=phase,
        forecast_origin=origin.isoformat(),
    )


def scientific_lightgbm_parameters(parameters: dict) -> dict:
    """Exclude execution-only parallelism from the scientific model identity."""
    return {key: value for key, value in parameters.items() if key != "num_threads"}


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

    from hqai_ml.features.data import connect
    from hqai_ml.features.load import load_panels
    from hqai_ml.flow_forecast.config import load_flow_config
    from hqai_ml.flow_forecast.evidence import (
        assert_temporal_boundaries,
        audit_data,
        evaluate_origin,
        extrapolation_diagnostics,
        forecast_hierarchy_diagnostics,
        hierarchy_diagnostics,
        national_panel,
        summarize_evaluation,
        validation_recommendation,
    )
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.models.config import load_model_config
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun, build_plan
    from hqai_ml.registry.resources import seed_process

    root = Path(__file__).resolve().parents[2]
    settings = IngestSettings()
    config_path = settings.configs_dir / "flow_forecast.yaml"
    config = load_flow_config(config_path)
    model_config = load_model_config(settings)
    if model_config.load_forecast.horizon != config.horizon:
        raise ValueError("flow evidence horizon must match the current Poisson LightGBM feature contract")
    model_config.lightgbm = {**model_config.lightgbm, "num_threads": resources.model_threads}
    seed_process(config.seed)
    protocol = {
        "origin_semantics": "last_observed_day",
        "horizons": list(range(1, config.horizon + 1)),
        "validation_origins": [str(origin) for origin in config.validation_origins],
        "validation_target_end": str(config.validation_origins[-1] + dt.timedelta(days=config.horizon)),
        "final_test_origin": str(config.final_test_origin),
        "final_test_start": str(config.final_test_origin + dt.timedelta(days=1)),
        "final_test_used_for_selection": False,
        "rolling_origin_only": True,
    }
    plan = build_plan(
        root=root,
        processed_dir=settings.processed_dir,
        configs_dir=settings.configs_dir,
        selected_models=["load_forecast"],
        resources=resources,
        temporal_protocols={"flow_forecast_evidence": protocol},
        hyperparameters={
            "lightgbm": scientific_lightgbm_parameters(model_config.lightgbm),
            "fixed_poisson_challenger": model_config.load_forecast.model_dump(mode="json"),
            "flow_forecast": config.model_dump(mode="json", exclude={"identity_sha256"}),
        },
        configuration_paths=[config_path, settings.configs_dir / "models.yaml", settings.configs_dir / "ingest.yaml"],
    )
    if args.plan:
        print(
            store.canonical_json(
                {
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "dataset_identity": plan["dataset"]["identity_sha256"],
                    "config_identity": plan["configuration"]["sha256"],
                    "code_identity": plan["code"]["source"]["sha256"],
                    "protocol": protocol,
                    "resources": plan["execution"]["resources"],
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
        log(f"run {run_id}; automatic promotion disabled")
        con = connect(settings.processed_dir, resources)
        hospital, region = load_panels(con)
        panels = {"hospital": hospital, "region": region, "national": national_panel(region)}
        assert_temporal_boundaries(hospital, config)
        audit = audit_data(
            con,
            settings.processed_dir.relative_to(root) / "_manifest.json",
            panels,
            config,
        )
        hierarchy = hierarchy_diagnostics(panels)
        con.close()

        phases = [(origin, "validation") for origin in config.validation_origins]
        phases.append((config.final_test_origin, "final_test"))
        frames = []
        origin_resources = []
        reused = 0
        parameters = {
            "challenger": config.challenger.id,
            "fixed_rounds": model_config.load_forecast.rounds,
            "objective": model_config.load_forecast.objective,
            "feature_contract": "hqai_ml.features.load",
            "tuning": False,
        }
        for origin, phase in phases:
            key = origin_key(origin, phase)
            origin_keys.append(key)
            parameters_by_key[key.identifier] = parameters
            checkpoint = run.reusable_checkpoint(key, parameters=parameters)
            if checkpoint:
                artifact = settings.artifacts_dir / checkpoint["artifact"]["path"]
                frames.append(pd_read_parquet(artifact / "evaluation.parquet"))
                origin_resources.append(json.loads((artifact / "metadata.json").read_text(encoding="utf-8")))
                reused += 1
                log(f"reuse {phase} origin {origin} checkpoint")
                continue
            run.start_checkpoint(key, parameters=parameters)
            origin_started = time.perf_counter()
            try:
                log(f"evaluate {phase} origin {origin}")
                frame = evaluate_origin(panels, origin, phase, config, model_config)
                elapsed = time.perf_counter() - origin_started
                metadata = {
                    "origin": str(origin),
                    "phase": phase,
                    "runtime_seconds": elapsed,
                    "peak_memory_mib": peak_memory_mib(),
                    "rows": len(frame),
                }

                def write_origin(
                    directory: Path,
                    result=frame,
                    result_metadata=metadata,
                ) -> None:
                    result.to_parquet(directory / "evaluation.parquet", index=False, compression="zstd")
                    (directory / "metadata.json").write_text(store.canonical_json(result_metadata), encoding="utf-8")

                artifact, artifact_manifest = store.publish_artifact_directory(
                    settings.artifacts_dir / "flow_forecast" / run_id / "origins",
                    f"{phase}-{origin}",
                    write_origin,
                )
                checkpoint_metrics = {
                    "runtime_seconds": elapsed,
                    "peak_memory_mib": metadata["peak_memory_mib"],
                    "rows": len(frame),
                    "final_test_used_for_selection": False,
                }
                run.complete_checkpoint(
                    key,
                    parameters=parameters,
                    metrics=checkpoint_metrics,
                    evaluation_status="completed",
                    artifact_path=artifact,
                    artifact_sha256=artifact_manifest["content_sha256"],
                    version=f"{phase}-{origin}",
                )
                frames.append(frame)
                origin_resources.append(metadata)
            except KeyboardInterrupt:
                run.interrupt_checkpoint(key)
                raise
            except BaseException as exc:
                run.fail_checkpoint(key, exc, root)
                raise

        import pandas as pd

        evaluation = pd.concat(frames, ignore_index=True)
        metrics = summarize_evaluation(evaluation)
        recommendation = validation_recommendation(metrics, config.challenger.id)
        extrapolation = extrapolation_diagnostics(
            evaluation,
            config.challenger.id,
            config.extrapolation_report_ratio_threshold,
            config.extrapolation_examples,
        )
        summary = {
            "schema_version": 1,
            "run_id": run_id,
            "scientific_identity_sha256": plan["scientific_identity_sha256"],
            "identity": {
                "dataset": plan["dataset"]["identity_sha256"],
                "configuration": plan["configuration"]["sha256"],
                "code": plan["code"]["source"]["sha256"],
                "flow_config": config.identity_sha256,
            },
            "protocol": protocol,
            "origins": [{"origin": str(origin), "phase": phase} for origin, phase in phases],
            "data_audit": audit,
            "candidate": {
                "id": config.challenger.id,
                "objective": "poisson",
                "fixed_configuration": True,
                "feature_semantics_changed": False,
                "tuned": False,
                "training_levels": ["hospital", "region"],
                "national_forecast": "exact sum of region predictions; not in LightGBM training population",
            },
            "metrics": metrics,
            "hierarchy": hierarchy,
            "forecast_hierarchy": forecast_hierarchy_diagnostics(evaluation, config.challenger.id),
            "extrapolation_diagnostics": extrapolation,
            "stability_evidence": {
                "profile_thread_count_restored": True,
                "thread_count_is_execution_metadata": True,
                "observed_assertion_at_thread_counts": [1, 4],
                "code_change_preceding_stable_run": (
                    "national/profile series were removed from the LightGBM training population and national "
                    "forecasts were instead derived from region predictions"
                ),
                "root_cause_established": False,
            },
            "resource_use": {
                "profile": args.profile,
                "model_threads": resources.model_threads,
                "origins": origin_resources,
                "runtime_seconds": time.perf_counter() - STARTED,
                "peak_memory_mib": peak_memory_mib(),
                "reused_checkpoints": reused,
            },
            "recommendation": recommendation,
        }
        summary_key = CheckpointKey.model("load_forecast")
        summary_parameters = {
            "evidence_summary": True,
            "origin_checkpoint_ids": [key.identifier for key in origin_keys],
        }
        parameters_by_key[summary_key.identifier] = summary_parameters
        existing_summary = run.reusable_checkpoint(summary_key, parameters=summary_parameters)
        if existing_summary is None:
            run.start_checkpoint(summary_key, parameters=summary_parameters)

            def write_summary(directory: Path) -> None:
                (directory / "summary.json").write_text(store.canonical_json(summary), encoding="utf-8")

            summary_dir, manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "flow_forecast" / run_id / "summaries",
                "evidence-summary",
                write_summary,
            )
            run.complete_checkpoint(
                summary_key,
                parameters=summary_parameters,
                metrics={
                    "recommendation": recommendation["promotion"],
                    "recommendation_reason": recommendation["reason"],
                    "validation_origins": len(config.validation_origins),
                    "final_test_origins": 1,
                    "reused_checkpoints": reused,
                },
                evaluation_status="completed",
                artifact_path=summary_dir,
                artifact_sha256=manifest["content_sha256"],
                version="evidence-summary",
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
            run.fail(exc, Path(__file__).resolve().parents[2])
        raise
    finally:
        if run is not None:
            run.release_lock()


def pd_read_parquet(path: Path):
    import pandas as pd

    return pd.read_parquet(path)


if __name__ == "__main__":
    raise SystemExit(main())
