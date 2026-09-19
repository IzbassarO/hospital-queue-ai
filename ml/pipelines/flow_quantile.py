#!/usr/bin/env python3
"""Prepare/run non-promoting p10/p50/p90 flow evidence with resumable origins."""

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


def quantile_origin_key(origin: dt.date, phase: str):
    from hqai_ml.registry.experiment import CheckpointKey

    return CheckpointKey(
        "load_forecast",
        candidate_id="flow-quantile-evidence",
        trial_id="fixed",
        fold_id=phase,
        forecast_origin=origin.isoformat(),
    )


def scientific_lightgbm_parameters(parameters: dict) -> dict:
    return {key: value for key, value in parameters.items() if key != "num_threads"}


def temporal_protocol(config) -> dict:
    return {
        "origin_semantics": "last_observed_day",
        "horizons": list(range(1, config.horizon + 1)),
        "validation_origins": [str(origin) for origin in config.validation_origins],
        "validation_target_end": str(config.validation_origins[-1] + dt.timedelta(days=config.horizon)),
        "final_test_origin": str(config.final_test_origin),
        "final_test_start": str(config.final_test_origin + dt.timedelta(days=1)),
        "final_test_used_for_selection_or_calibration": False,
        "rolling_origin_only": True,
    }


def calibration_identity(config) -> str:
    payload = {
        "baseline": "recent_seasonal_average",
        "residual_uncertainty": config.residual_uncertainty.model_dump(mode="json"),
        "quantiles": config.challenger.quantiles,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def build_quantile_plan(root, settings, resources, config, model_config) -> tuple[dict, dict, str]:
    from hqai_ml.registry.experiment import build_plan

    protocol = temporal_protocol(config)
    residual_calibration_id = calibration_identity(config)
    plan = build_plan(
        root=root,
        processed_dir=settings.processed_dir,
        configs_dir=settings.configs_dir,
        selected_models=["load_forecast"],
        resources=resources,
        temporal_protocols={"flow_quantile_evidence": protocol},
        hyperparameters={
            "lightgbm": scientific_lightgbm_parameters(model_config.lightgbm),
            "quantile_model": {
                "objective": "quantile",
                "alphas": config.challenger.quantiles,
                "rounds": config.challenger.rounds,
                "feature_contract": "hqai_ml.features.load",
                "search_configurations": 1,
            },
            "calibration": {
                "identity": residual_calibration_id,
                **config.residual_uncertainty.model_dump(mode="json"),
            },
            "flow_quantile": config.model_dump(mode="json", exclude={"identity_sha256"}),
        },
        configuration_paths=[
            settings.configs_dir / "flow_quantile.yaml",
            settings.configs_dir / "models.yaml",
            settings.configs_dir / "ingest.yaml",
        ],
    )
    return plan, protocol, residual_calibration_id


def public_target_audit(audit: dict) -> dict:
    converted = dict(audit)
    converted["coverage"] = [
        row | {"target": "cohort_hospitalizations" if row["target"] == "hospitalizations" else row["target"]}
        for row in audit["coverage"]
    ]
    semantics = dict(audit["target_semantics"])
    semantics["cohort_hospitalizations"] = semantics.pop("hospitalizations")
    converted["target_semantics"] = semantics
    return converted


def public_hierarchy_diagnostics(diagnostics: dict) -> dict:
    converted = dict(diagnostics)
    checks = dict(diagnostics["aggregation_checks"])
    checks["cohort_hospitalizations"] = checks.pop("hospitalizations")
    converted["aggregation_checks"] = checks
    return converted


def ersb_readiness(con) -> dict:
    columns = con.execute("DESCRIBE ersb_snapshot").df()["column_name"].tolist()
    rows, org_codes, first_load, last_load = con.execute(
        """SELECT count(*), count(*) FILTER (WHERE org_code IS NOT NULL),
                  min(sdu_load_date), max(sdu_load_date)
           FROM ersb_snapshot"""
    ).fetchone()
    return {
        "present": True,
        "rows": int(rows),
        "granularity": "one static snapshot row per ERSB organization record",
        "treated_case_date_span": None,
        "snapshot_load_timestamp_span": [str(first_load), str(last_load)],
        "period_status": "unknown; sdu_load_date is ingestion freshness, not a treatment-period field",
        "hospital_identifier": {
            "ersb_id": "available",
            "matched_org_code": "available for matched rows",
            "matched_rows": int(org_codes),
        },
        "profile_available": False,
        "columns": columns,
        "used_for_quantile_training": False,
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

    from hqai_ml.features.data import connect
    from hqai_ml.features.load import load_panels
    from hqai_ml.flow_forecast.config import load_flow_quantile_config
    from hqai_ml.flow_forecast.evidence import (
        assert_temporal_boundaries,
        audit_data,
        hierarchy_diagnostics,
        national_panel,
    )
    from hqai_ml.flow_forecast.quantile import (
        BASELINE,
        NATIONAL_PROXY,
        RAW_VARIANT,
        REPAIRED_VARIANT,
        evaluate_quantile_origin,
        presentation_examples,
        quantile_extrapolation_diagnostics,
        summarize_probabilistic_evaluation,
        validation_retention,
    )
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.models.config import load_model_config
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun
    from hqai_ml.registry.resources import seed_process

    root = Path(__file__).resolve().parents[2]
    settings = IngestSettings()
    config_path = settings.configs_dir / "flow_quantile.yaml"
    config = load_flow_quantile_config(config_path)
    model_config = load_model_config(settings)
    if model_config.load_forecast.horizon != config.horizon:
        raise ValueError("quantile horizon must match the existing load feature contract")
    model_config.lightgbm = {**model_config.lightgbm, "num_threads": resources.model_threads}
    seed_process(config.seed)
    plan, protocol, calibration_id = build_quantile_plan(root, settings, resources, config, model_config)
    if args.plan:
        print(
            store.canonical_json(
                {
                    "workflow": "flow_quantile_evidence",
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "dataset_identity": plan["dataset"]["identity_sha256"],
                    "configuration_identity": plan["configuration"]["sha256"],
                    "code_identity": plan["code"]["source"]["sha256"],
                    "calibration_identity": calibration_id,
                    "protocol": protocol,
                    "resources": plan["execution"]["resources"],
                    "origin_checkpoints": [
                        quantile_origin_key(origin, phase).to_dict()
                        for origin, phase in [
                            *((origin, "validation") for origin in config.validation_origins),
                            (config.final_test_origin, "final_test"),
                        ]
                    ],
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
        audit = public_target_audit(
            audit_data(
                con,
                settings.processed_dir.relative_to(root) / "_manifest.json",
                panels,
                config,
            )
        )
        ersb = ersb_readiness(con)
        hierarchy = public_hierarchy_diagnostics(hierarchy_diagnostics(panels))
        hierarchy.update(
            {
                "national_probabilistic_output": NATIONAL_PROXY,
                "probabilistic_reconciliation_applied": False,
                "national_proxy_interpretation": (
                    "coverage and WIS describe the interval formed by sums of corresponding region quantiles; "
                    "they do not describe a reconciled national predictive distribution"
                ),
            }
        )
        con.close()

        phases = [(origin, "validation") for origin in config.validation_origins]
        phases.append((config.final_test_origin, "final_test"))
        frames = []
        origin_resources = []
        calibration_audits = []
        reused = 0
        parameters = {
            "candidates": [BASELINE, config.challenger.id],
            "quantiles": config.challenger.quantiles,
            "rounds": config.challenger.rounds,
            "search_configurations": 1,
            "calibration_identity": calibration_id,
            "tuning": False,
        }
        for origin, phase in phases:
            key = quantile_origin_key(origin, phase)
            origin_keys.append(key)
            parameters_by_key[key.identifier] = parameters
            checkpoint = run.reusable_checkpoint(key, parameters=parameters)
            if checkpoint:
                artifact = settings.artifacts_dir / checkpoint["artifact"]["path"]
                frames.append(pd.read_parquet(artifact / "evaluation.parquet"))
                metadata = json.loads((artifact / "metadata.json").read_text(encoding="utf-8"))
                origin_resources.append(metadata["resources"])
                calibration_audits.extend(metadata["calibration_audits"])
                reused += 1
                log(f"reuse {phase} origin {origin} checkpoint")
                continue
            run.start_checkpoint(key, parameters=parameters)
            origin_started = time.perf_counter()
            try:
                log(f"evaluate {phase} origin {origin}")
                frame, origin_calibration = evaluate_quantile_origin(
                    panels,
                    origin,
                    phase,
                    config,
                    model_config,
                    calibration_id,
                )
                elapsed = time.perf_counter() - origin_started
                metadata = {
                    "resources": {
                        "origin": str(origin),
                        "phase": phase,
                        "runtime_seconds": elapsed,
                        "peak_memory_mib": peak_memory_mib(),
                        "rows": len(frame),
                        "model_threads": resources.model_threads,
                    },
                    "calibration_audits": origin_calibration,
                }

                def write_origin(
                    directory: Path,
                    result=frame,
                    result_metadata=metadata,
                ) -> None:
                    result.to_parquet(directory / "evaluation.parquet", index=False, compression="zstd")
                    (directory / "metadata.json").write_text(store.canonical_json(result_metadata), encoding="utf-8")

                artifact, manifest = store.publish_artifact_directory(
                    settings.artifacts_dir / "flow_quantile" / run_id / "origins",
                    f"{phase}-{origin}",
                    write_origin,
                )
                run.complete_checkpoint(
                    key,
                    parameters=parameters,
                    metrics={
                        "runtime_seconds": elapsed,
                        "peak_memory_mib": metadata["resources"]["peak_memory_mib"],
                        "rows": len(frame),
                        "final_test_used_for_selection_or_calibration": False,
                    },
                    evaluation_status="completed",
                    artifact_path=artifact,
                    artifact_sha256=manifest["content_sha256"],
                    version=f"{phase}-{origin}",
                )
                frames.append(frame)
                origin_resources.append(metadata["resources"])
                calibration_audits.extend(origin_calibration)
            except KeyboardInterrupt:
                run.interrupt_checkpoint(key)
                raise
            except BaseException as exc:
                run.fail_checkpoint(key, exc, root)
                raise

        evaluation = pd.concat(frames, ignore_index=True)
        metrics = summarize_probabilistic_evaluation(evaluation)
        retention = validation_retention(metrics, config.challenger.id)
        extrapolation = quantile_extrapolation_diagnostics(
            evaluation,
            config.extrapolation_report_ratio_threshold,
            config.extrapolation_examples,
        )
        demos = presentation_examples(
            evaluation,
            config.challenger.id,
            {
                "observed_date_end": str(hospital.dates[-1]),
                "source_manifest": audit["source_manifest"],
                "dataset_identity": plan["dataset"]["identity_sha256"],
            },
            config.extrapolation_report_ratio_threshold,
        )
        summary = {
            "schema_version": 1,
            "run_id": run_id,
            "scientific_identity_sha256": plan["scientific_identity_sha256"],
            "identity": {
                "dataset": plan["dataset"]["identity_sha256"],
                "configuration": plan["configuration"]["sha256"],
                "code": plan["code"]["source"]["sha256"],
                "flow_quantile_config": config.identity_sha256,
                "calibration": calibration_id,
            },
            "protocol": protocol,
            "origins": [{"origin": str(origin), "phase": phase} for origin, phase in phases],
            "targets": {
                "primary": "registrations: daily referral inflow",
                "secondary": (
                    "cohort_hospitalizations: hospitalization events belonging to the Q1 referral cohort; "
                    "not total admissions, occupancy, free beds, or physical capacity"
                ),
            },
            "data_audit": audit,
            "ersb_readiness": ersb,
            "candidates": {
                BASELINE: {
                    "point_anchor": "recent_seasonal_average",
                    "uncertainty": config.residual_uncertainty.model_dump(mode="json"),
                    "calibration_identity": calibration_id,
                },
                config.challenger.id: {
                    "objective": "three independent LightGBM quantile objectives",
                    "alphas": config.challenger.quantiles,
                    "configurations": 1,
                    "feature_semantics_changed": False,
                },
            },
            "variants": {
                "primary_scientific_evidence": RAW_VARIANT,
                "retention_metric_variant": RAW_VARIANT,
                "repaired_metrics_govern_retention": False,
                RAW_VARIANT: "unmodified outputs; primary validation and final-test scientific evidence",
                REPAIRED_VARIANT: (
                    "secondary serving/UI diagnostic only: explicit max(0) then cumulative-maximum projection"
                ),
            },
            "calibration_audits": calibration_audits,
            "metrics": metrics,
            "hierarchy": hierarchy,
            "extrapolation_diagnostics": extrapolation,
            "retention_recommendation": retention,
            "resource_use": {
                "profile": args.profile,
                "model_threads": resources.model_threads,
                "origins": origin_resources,
                "runtime_seconds": time.perf_counter() - STARTED,
                "peak_memory_mib": peak_memory_mib(),
                "reused_checkpoints": reused,
            },
            "automatic_promotion": False,
        }
        summary_key = CheckpointKey.model("load_forecast")
        summary_parameters = {
            "probabilistic_evidence_summary": True,
            "origin_checkpoint_ids": [key.identifier for key in origin_keys],
        }
        parameters_by_key[summary_key.identifier] = summary_parameters
        existing_summary = run.reusable_checkpoint(summary_key, parameters=summary_parameters)
        if existing_summary is None:
            run.start_checkpoint(summary_key, parameters=summary_parameters)

            def write_summary(directory: Path) -> None:
                (directory / "summary.json").write_text(store.canonical_json(summary), encoding="utf-8")
                (directory / "presentation-examples.json").write_text(store.canonical_json(demos), encoding="utf-8")

            summary_dir, manifest = store.publish_artifact_directory(
                settings.artifacts_dir / "flow_quantile" / run_id / "summaries",
                "quantile-summary",
                write_summary,
            )
            run.complete_checkpoint(
                summary_key,
                parameters=summary_parameters,
                metrics={
                    "retention_outcome": retention["outcome"],
                    "validation_only": True,
                    "automatic_promotion": False,
                    "reused_checkpoints": reused,
                },
                evaluation_status="completed",
                artifact_path=summary_dir,
                artifact_sha256=manifest["content_sha256"],
                version="quantile-summary",
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
