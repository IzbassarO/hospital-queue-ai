#!/usr/bin/env python3
"""Run the reviewed patient-journey survival tournament without promoting any model."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from hqai_ml.registry.resources import apply_resource_environment, resource_config

T0 = time.time()


def log(message: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {message}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "laptop", "overnight"), default="smoke")
    parser.add_argument("--run-id")
    parser.add_argument("--resume", metavar="RUN_ID")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--audit-events-only", action="store_true")
    parser.add_argument("--final-confirmation", action="store_true")
    parser.add_argument("--source-run", metavar="RUN_ID")
    parser.add_argument("--full-cohort", action="store_true")
    args = parser.parse_args()

    if args.final_confirmation:
        if not args.source_run or not args.full_cohort:
            parser.error("--final-confirmation requires --source-run RUN_ID and --full-cohort")
        if args.profile != "overnight":
            parser.error("full-cohort confirmation must use the existing overnight resource profile")
    elif args.source_run or args.full_cohort:
        parser.error("--source-run and --full-cohort are valid only with --final-confirmation")

    resources = resource_config(args.profile, parallel_trials=1 if args.final_confirmation else None)
    apply_resource_environment(resources)

    from hqai_ml.evaluation.metrics import regression_metrics
    from hqai_ml.features.data import connect
    from hqai_ml.features.referral import build_referral_features
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun, build_plan
    from hqai_ml.tournament.candidates import empirical_competing_probabilities, legacy_wait_probabilities
    from hqai_ml.tournament.config import deterministic_trials, load_tournament_config
    from hqai_ml.tournament.evaluation import (
        calibrate_hospitalization,
        calibrate_journey,
        hpo_objective,
        journey_metrics,
        subgroup_assurance,
    )
    from hqai_ml.tournament.labels import (
        EVENT_HOSPITALIZED,
        construct_journey_labels,
        recensor_at,
        split_by_period,
    )
    from hqai_ml.tournament.refusal import refusal_benchmarks

    root = Path(__file__).resolve().parents[2]
    settings = IngestSettings()
    config_path = settings.configs_dir / "tournament.yaml"
    config = load_tournament_config(config_path)
    profile = config.profiles[args.profile]
    folds = [fold for fold in config.folds if fold.id in profile.folds]
    source_evidence = None
    if args.final_confirmation:
        source_evidence = load_confirmation_evidence(settings.artifacts_dir, args.source_run, config)
        enabled = list(source_evidence["finalists"])
    else:
        enabled = [name for name, candidate in config.candidates.items() if candidate.enabled]
    con = connect(settings.processed_dir, resources)
    features = build_referral_features(con, config.folds[0].train[0])
    event_fields = con.execute(
        """SELECT referral_id, registration_dt, hospitalization_dt, refusal_dt,
                  is_dup_code, outcome_conflict
           FROM fact_referral ORDER BY referral_id"""
    ).df()
    frame = features.merge(event_fields, on="referral_id", how="left", validate="one_to_one")
    labels = construct_journey_labels(frame, config.label_contract)
    log(
        "event audit: "
        + json.dumps(
            {key: value for key, value in labels.audit.items() if key != "cohort_by_dimension"},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if args.audit_events_only:
        return 0

    data = labels.rows
    if not args.final_confirmation and profile.sample_rows is not None and len(data) > profile.sample_rows:
        data = data.sample(profile.sample_rows, random_state=config.seed).sort_values(
            ["registration_date", "referral_id"]
        )
        data = data.reset_index(drop=True)
    protocol = {
        "mode": "full_cohort_final_confirmation" if args.final_confirmation else "tournament",
        "label_cutoff": config.label_contract.cutoff.isoformat(),
        "horizons": config.horizons,
        "folds": [fold.model_dump(mode="json") for fold in folds],
        "split_order": ["train", "validation", "calibration", "test"],
        "final_test_used_for_hpo": False,
        "hyperparameter_selection_in_confirmation": False,
    }
    confirmation_hyperparameters = None
    if source_evidence is not None:
        confirmation_hyperparameters = {
            "source_run": args.source_run,
            "source_summary_sha256": source_evidence["source_summary_sha256"],
            "full_cohort": True,
            "finalists": source_evidence["finalists"],
            "refusal_classifier": source_evidence["refusal_classifier"],
        }
    plan = build_plan(
        root=root,
        processed_dir=settings.processed_dir,
        configs_dir=settings.configs_dir,
        selected_models=["patient_journey"],
        resources=resources,
        temporal_protocols={"patient_journey": protocol},
        hyperparameters={
            "lightgbm": {"seed": config.seed},
            "tournament": config.model_dump(mode="json"),
            "profile": args.profile,
            "final_confirmation": confirmation_hyperparameters,
        },
        configuration_paths=[config_path, settings.configs_dir / "models.yaml", settings.configs_dir / "ingest.yaml"],
    )
    if args.plan:
        print(
            store.canonical_json(
                {
                    "config_identity": config.identity_sha256,
                    "scientific_identity": plan["scientific_identity_sha256"],
                    "profile": args.profile,
                    "resources": plan["execution"]["resources"],
                    "sample_rows": len(data),
                    "candidates": enabled,
                    "folds": [fold.id for fold in folds],
                    "automatic_promotion": False,
                    "mode": protocol["mode"],
                    "source_run": args.source_run,
                }
            ),
            end="",
        )
        return 0

    if args.final_confirmation:
        return run_final_confirmation(
            args=args,
            root=root,
            settings=settings,
            config=config,
            resources=resources,
            folds=folds,
            data=data,
            audit=labels.audit,
            plan=plan,
            source_evidence=source_evidence,
        )

    run = None
    checkpoint_keys: list[CheckpointKey] = []
    checkpoint_parameters: dict[str, dict] = {}
    reused = 0
    results = []
    exclusions = []
    selections = []
    current_manifest = settings.artifacts_dir / "models" / store.MANIFEST
    manifest_sha_before = store.sha256_file(current_manifest) if current_manifest.exists() else None
    try:
        run = ExperimentRun.start(settings.artifacts_dir, plan, run_id=args.run_id, resume_run_id=args.resume)
        run_id = run.manifest["run_id"]
        log(f"run: {run_id}; sampled eligible rows: {len(data):,}")
        fold_parts = {}
        for fold in folds:
            fold_parts[fold.id] = {
                name: split_by_period(data, getattr(fold, name))
                for name in ("train", "validation", "calibration", "test")
            }
            log(
                f"fold {fold.id}: " + ", ".join(f"{name}={len(value):,}" for name, value in fold_parts[fold.id].items())
            )

        for candidate in enabled:
            estimand = candidate_estimand(candidate)
            compatible_folds = []
            for fold in folds:
                eligible, reason = legacy_fold_eligibility(candidate, fold, config.legacy_artifacts_trained_through)
                if eligible:
                    compatible_folds.append(fold)
                else:
                    exclusions.append(
                        {
                            "candidate": candidate,
                            "fold": fold.id,
                            "status": "excluded",
                            "reason": reason,
                            "estimand": estimand,
                        }
                    )
            if not compatible_folds:
                log(f"candidate {candidate}: excluded from all selected folds (legacy training-window overlap)")
                continue

            search = deterministic_trials(config, candidate, profile.max_trials)
            trial_aggregates = []
            for number, parameters in enumerate(search):
                trial_id = f"trial-{number:03d}"
                fold_records = []
                for fold in compatible_folds:
                    parts = fold_parts[fold.id]
                    key = CheckpointKey("patient_journey", candidate, trial_id, fold.id)
                    checkpoint_keys.append(key)
                    checkpoint_parameters[key.identifier] = parameters
                    existing = run.reusable_checkpoint(key, parameters=parameters)
                    if existing:
                        reused += 1
                        fold_records.append({"fold": fold.id, **existing["metrics"]})
                        continue
                    run.start_checkpoint(key, parameters=parameters)
                    started = time.time()
                    try:
                        validation_probabilities, _, model_info = fit_and_predict(
                            candidate,
                            parts["train"],
                            parts["validation"],
                            None,
                            parameters,
                            config,
                            resources,
                            settings.artifacts_dir,
                            profile.round_cap,
                        )
                        hospitalization_only = candidate in {
                            "legacy_wait_regression",
                            "xgboost_aft",
                            "discrete_hospitalization_hazard",
                        }
                        objective, metrics = hpo_objective(
                            parts["validation"],
                            validation_probabilities,
                            hospitalization_only=hospitalization_only,
                        )
                        model_info.pop("model_object", None)
                        record = {
                            "validation_primary_metric": objective,
                            "primary_metric_name": metrics["primary_metric_name"],
                            "estimand": metrics["estimand"],
                            "validation": metrics,
                            "runtime_seconds": time.time() - started,
                            "model": model_info,
                        }
                        run.complete_checkpoint(
                            key, parameters=parameters, metrics=record, evaluation_status="completed"
                        )
                        fold_records.append({"fold": fold.id, **record})
                    except KeyboardInterrupt:
                        run.interrupt_checkpoint(key)
                        raise
                    except BaseException as exc:
                        run.fail_checkpoint(key, exc, root)
                        raise

                trial_aggregates.append(
                    {
                        "trial_id": trial_id,
                        "parameters": parameters,
                        "folds": fold_records,
                        "mean_validation_primary_metric": float(
                            sum(row["validation_primary_metric"] for row in fold_records) / len(fold_records)
                        ),
                        "primary_metric_name": fold_records[0]["primary_metric_name"],
                        "estimand": fold_records[0]["estimand"],
                    }
                )

            best = select_cross_fold_trial(trial_aggregates)
            best_parameters = best["parameters"]
            selections.append(best)
            log(
                f"candidate {candidate}: {best['trial_id']} selected across {len(compatible_folds)} fold(s); "
                f"mean validation {best['primary_metric_name']}={best['mean_validation_primary_metric']:.6f}"
            )
            for fold in compatible_folds:
                parts = fold_parts[fold.id]
                baseline = empirical_competing_probabilities(
                    parts["train"],
                    parts["test"],
                    config.horizons,
                    config.group_baseline.columns,
                    config.group_baseline.min_support,
                )
                calibration_key = CheckpointKey(
                    "patient_journey", f"{candidate}-calibration", best["trial_id"], fold.id
                )
                selected_key = CheckpointKey("patient_journey", candidate, "selected", fold.id)
                checkpoint_keys.extend([calibration_key, selected_key])
                checkpoint_parameters[calibration_key.identifier] = best_parameters
                checkpoint_parameters[selected_key.identifier] = best_parameters
                selected_checkpoint = run.reusable_checkpoint(selected_key, parameters=best_parameters)
                calibration_checkpoint = run.reusable_checkpoint(calibration_key, parameters=best_parameters)
                if selected_checkpoint and calibration_checkpoint:
                    reused += 2
                    result = load_result_artifact(settings.artifacts_dir, selected_checkpoint)
                    results.append(result)
                    continue

                if not calibration_checkpoint:
                    run.start_checkpoint(calibration_key, parameters=best_parameters)
                if not selected_checkpoint:
                    run.start_checkpoint(selected_key, parameters=best_parameters)
                started = time.time()
                try:
                    calibration_raw, test_raw, model_info = fit_and_predict(
                        candidate,
                        parts["train"],
                        parts["calibration"],
                        parts["test"],
                        best_parameters,
                        config,
                        resources,
                        settings.artifacts_dir,
                        profile.round_cap,
                        validation=parts["validation"],
                    )
                    model_object = model_info.pop("model_object", None)
                    hospitalization_only = candidate in {
                        "legacy_wait_regression",
                        "xgboost_aft",
                        "discrete_hospitalization_hazard",
                    }
                    if hospitalization_only:
                        calibrated, calibration_evidence = calibrate_hospitalization(
                            parts["calibration"], calibration_raw, test_raw
                        )
                    else:
                        calibrated, calibration_evidence = calibrate_journey(
                            parts["calibration"], calibration_raw, test_raw
                        )
                    if not calibration_checkpoint:
                        run.complete_checkpoint(
                            calibration_key,
                            parameters=best_parameters,
                            metrics=calibration_evidence,
                            evaluation_status="completed",
                        )
                    else:
                        calibration_evidence = calibration_checkpoint["metrics"]
                    metrics = journey_metrics(parts["test"], calibrated, hospitalization_only=hospitalization_only)
                    assurance = subgroup_assurance(
                        parts["test"],
                        calibrated,
                        baseline,
                        config.support_buckets,
                        hospitalization_only=hospitalization_only,
                    )
                    result = {
                        "candidate": candidate,
                        "fold": fold.id,
                        "best_trial": best["trial_id"],
                        "best_parameters": best_parameters,
                        "cross_fold_validation_primary_metric": best["mean_validation_primary_metric"],
                        "primary_metric_name": metrics["primary_metric_name"],
                        "estimand": metrics["estimand"],
                        "test_metrics": metrics,
                        "calibration": calibration_evidence,
                        "subgroup_assurance": assurance,
                        "runtime_seconds": time.time() - started,
                        "model": model_info,
                        "limitations": candidate_limitations(candidate),
                    }
                    strict_parts = {
                        name: part[part["journey_strict_timestamp_eligible"]].reset_index(drop=True)
                        for name, part in parts.items()
                    }
                    strict_calibration_raw, strict_test_raw, _ = fit_and_predict(
                        candidate,
                        strict_parts["train"],
                        strict_parts["calibration"],
                        strict_parts["test"],
                        best_parameters,
                        config,
                        resources,
                        settings.artifacts_dir,
                        profile.round_cap,
                        validation=strict_parts["validation"],
                    )
                    if hospitalization_only:
                        strict_calibrated, strict_calibration = calibrate_hospitalization(
                            strict_parts["calibration"], strict_calibration_raw, strict_test_raw
                        )
                    else:
                        strict_calibrated, strict_calibration = calibrate_journey(
                            strict_parts["calibration"], strict_calibration_raw, strict_test_raw
                        )
                    result["strict_timestamp_order_sensitivity"] = {
                        "cohort_rows": {name: len(part) for name, part in strict_parts.items()},
                        "calibration": strict_calibration,
                        "test_metrics": journey_metrics(
                            strict_parts["test"], strict_calibrated, hospitalization_only=hospitalization_only
                        ),
                    }
                    historical_train = recensor_at(parts["train"], fold.test[0])
                    historical_validation = recensor_at(parts["validation"], fold.test[0])
                    historical_probabilities, _, _ = fit_and_predict(
                        candidate,
                        historical_train,
                        parts["test"],
                        None,
                        best_parameters,
                        config,
                        resources,
                        settings.artifacts_dir,
                        profile.round_cap,
                        validation=historical_validation,
                    )
                    result["deployment_realistic_sensitivity"] = {
                        "labels_available_through": fold.test[0].isoformat(),
                        "training_rows_recensored": int(
                            (historical_train["journey_event"] != parts["train"]["journey_event"]).sum()
                        ),
                        "validation_rows_recensored": int(
                            (historical_validation["journey_event"] != parts["validation"]["journey_event"]).sum()
                        ),
                        "calibration": "not refit because late-fold labels lack full 30-day observability",
                        "test_metrics_uncalibrated": journey_metrics(
                            parts["test"], historical_probabilities, hospitalization_only=hospitalization_only
                        ),
                    }
                    if candidate == "legacy_wait_regression":
                        mask = (parts["test"]["journey_event"] == EVENT_HOSPITALIZED) & (
                            parts["test"]["journey_raw_duration_days"] >= 1
                        )
                        _, waits = legacy_wait_probabilities(settings.artifacts_dir, parts["test"], config.horizons)
                        result["legacy_completed_subset"] = regression_metrics(
                            parts["test"].loc[mask, "journey_raw_duration_days"].to_numpy(), waits[mask]
                        )
                    artifact_path, artifact_sha = write_result_artifact(
                        settings.artifacts_dir, run_id, selected_key, result, model_object
                    )
                    run.complete_checkpoint(
                        selected_key,
                        parameters=best_parameters,
                        metrics={
                            "test_primary_metric": metrics["primary_metric"],
                            "primary_metric_name": metrics["primary_metric_name"],
                            "estimand": metrics["estimand"],
                            "result": result,
                        },
                        artifact_path=artifact_path,
                        artifact_sha256=artifact_sha,
                        version=f"{candidate}-{fold.id}",
                        evaluation_status="completed",
                    )
                    results.append(result)
                except KeyboardInterrupt:
                    run.interrupt_checkpoint(selected_key)
                    raise
                except BaseException as exc:
                    run.fail_checkpoint(selected_key, exc, root)
                    raise

        final_fold = folds[-1]
        final_parts = fold_parts[final_fold.id]
        refusal_legacy_eligible, refusal_legacy_reason = legacy_fold_eligibility(
            "legacy_refusal_risk", final_fold, config.legacy_artifacts_trained_through
        )
        refusal = refusal_benchmarks(
            *[final_parts[name] for name in ("train", "validation", "calibration", "test")],
            settings.artifacts_dir,
            config.refusal_benchmarks,
            resources.model_threads,
            config.support_buckets[0],
            legacy_eligible=refusal_legacy_eligible,
            legacy_ineligibility_reason=refusal_legacy_reason,
        )
        manifest_sha_after = store.sha256_file(current_manifest) if current_manifest.exists() else None
        summary = tournament_summary(
            config,
            args.profile,
            run_id,
            labels.audit,
            len(data),
            results,
            refusal,
            reused,
            exclusions,
            selections,
            manifest_sha_before,
            manifest_sha_after,
        )
        summary_path = settings.artifacts_dir / "tournaments" / run_id / "tournament-summary.json"
        store.atomic_write_text(summary_path, store.canonical_json(summary))
        decision_path = settings.artifacts_dir / "tournaments" / run_id / "champion-decision.json"
        store.atomic_write_text(decision_path, store.canonical_json(summary["champion_decision"]))
        if run.manifest["status"] != "completed":
            run.complete(checkpoint_keys, parameters_by_key=checkpoint_parameters)
        log(f"summary: {summary_path.relative_to(root)}; reused checkpoints: {reused}")
        print(f"TOURNAMENT_RUN_ID={run_id}")
        return 0
    except KeyboardInterrupt:
        if run is not None:
            run.pause()
        raise
    except BaseException as exc:
        if run is not None:
            run.fail(exc, root)
        raise
    finally:
        if run is not None:
            run.release_lock()


def load_confirmation_evidence(artifacts_dir, source_run_id, config):
    """Load and cross-check frozen finalists from persisted tournament evidence."""
    from hqai_ml.registry import store

    summary_path = artifacts_dir / "tournaments" / source_run_id / "tournament-summary.json"
    run_path = artifacts_dir / "runs" / source_run_id / "run.json"
    if not summary_path.is_file() or not run_path.is_file():
        raise FileNotFoundError(f"source tournament evidence is incomplete for run {source_run_id!r}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    source_run = json.loads(run_path.read_text(encoding="utf-8"))
    if summary.get("run_id") != source_run_id or source_run.get("run_id") != source_run_id:
        raise ValueError("source tournament evidence has a mismatched run ID")
    if source_run.get("status") != "completed" or summary.get("profile") != "overnight":
        raise ValueError("final confirmation requires a completed overnight source tournament")
    if summary.get("config_identity") != config.identity_sha256:
        raise ValueError("source tournament configuration identity differs from the current reviewed config")

    finalists = {}
    for candidate in ("empirical_competing_risk", "xgboost_aft", "discrete_hospitalization_hazard"):
        rows = [row for row in summary.get("results", []) if row.get("candidate") == candidate]
        if not rows:
            raise ValueError(f"source tournament has no persisted result for finalist {candidate!r}")
        identities = {
            store.canonical_json({"trial_id": row.get("best_trial"), "parameters": row.get("best_parameters", {})})
            for row in rows
        }
        if len(identities) != 1:
            raise ValueError(f"source tournament did not use one frozen parameter set for {candidate!r}")
        selection = json.loads(next(iter(identities)))
        checkpoints = []
        for path in sorted((artifacts_dir / "runs" / source_run_id / "checkpoints").glob("*.json")):
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
            key = checkpoint.get("key", {})
            if (
                key.get("candidate_id") == candidate
                and key.get("trial_id") == "selected"
                and checkpoint.get("status") == "completed"
                and checkpoint.get("parameters") == selection["parameters"]
            ):
                checkpoints.append(checkpoint["key_id"])
        if len(checkpoints) != len(rows):
            raise ValueError(f"source selected checkpoints do not verify persisted parameters for {candidate!r}")
        finalists[candidate] = {**selection, "validated_source_checkpoint_ids": checkpoints}

    refusal_classifier = summary.get("refusal_benchmarks", {}).get("strongest_selected_on_validation")
    if refusal_classifier not in {"regularized_logistic", "fold_lightgbm"}:
        raise ValueError("source tournament has no valid persisted refusal-classifier selection")
    return {
        "source_run_id": source_run_id,
        "source_summary_path": summary_path,
        "source_summary_sha256": store.sha256_file(summary_path),
        "source_scientific_identity_sha256": source_run["scientific_identity_sha256"],
        "source_sampled_rows": summary["sampled_rows"],
        "finalists": finalists,
        "refusal_classifier": refusal_classifier,
    }


def _peak_rss_bytes() -> int:
    import resource

    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value * 1024 if sys.platform.startswith("linux") else value


def _calibration_ece(metrics: dict, target: str) -> float | None:
    values = []
    for row in metrics["by_horizon"].values():
        table = row["calibration"].get(target)
        if not table:
            continue
        total = sum(bin_row["n"] for bin_row in table)
        values.append(sum(bin_row["n"] * abs(bin_row["mean_pred"] - bin_row["observed"]) for bin_row in table) / total)
    return float(sum(values) / len(values)) if values else None


def _evaluate_frozen_candidate(candidate, parts, baseline, selection, config, resources, artifacts_dir, round_cap):
    from hqai_ml.tournament.evaluation import (
        calibrate_hospitalization,
        calibrate_journey,
        journey_metrics,
        subgroup_assurance,
    )
    from hqai_ml.tournament.labels import recensor_at

    started = time.time()
    peak_before = _peak_rss_bytes()
    hospitalization_only = candidate in {"xgboost_aft", "discrete_hospitalization_hazard"}
    parameters = selection["parameters"]
    calibration_raw, test_raw, model_info = fit_and_predict(
        candidate,
        parts["train"],
        parts["calibration"],
        parts["test"],
        parameters,
        config,
        resources,
        artifacts_dir,
        round_cap,
        validation=parts["validation"],
    )
    model_object = model_info.pop("model_object", None)
    calibration_fn = calibrate_hospitalization if hospitalization_only else calibrate_journey
    calibrated, calibration = calibration_fn(parts["calibration"], calibration_raw, test_raw)
    metrics = journey_metrics(parts["test"], calibrated, hospitalization_only=hospitalization_only)
    assurance = subgroup_assurance(
        parts["test"],
        calibrated,
        baseline,
        config.support_buckets,
        hospitalization_only=hospitalization_only,
    )

    strict_parts = {
        name: parts[name][parts[name]["journey_strict_timestamp_eligible"]].reset_index(drop=True)
        for name in ("train", "validation", "calibration", "test")
    }
    strict_calibration_raw, strict_test_raw, _ = fit_and_predict(
        candidate,
        strict_parts["train"],
        strict_parts["calibration"],
        strict_parts["test"],
        parameters,
        config,
        resources,
        artifacts_dir,
        round_cap,
        validation=strict_parts["validation"],
    )
    strict_calibrated, strict_calibration = calibration_fn(
        strict_parts["calibration"], strict_calibration_raw, strict_test_raw
    )
    strict_metrics = journey_metrics(strict_parts["test"], strict_calibrated, hospitalization_only=hospitalization_only)

    historical_train = recensor_at(parts["train"], parts["test"]["registration_date"].min())
    historical_validation = recensor_at(parts["validation"], parts["test"]["registration_date"].min())
    historical_probabilities, _, _ = fit_and_predict(
        candidate,
        historical_train,
        parts["test"],
        None,
        parameters,
        config,
        resources,
        artifacts_dir,
        round_cap,
        validation=historical_validation,
    )
    historical_metrics = journey_metrics(
        parts["test"], historical_probabilities, hospitalization_only=hospitalization_only
    )
    result = {
        "candidate": candidate,
        "fold": parts["fold_id"],
        "source_trial": selection["trial_id"],
        "frozen_parameters": parameters,
        "parameter_source_checkpoint_ids": selection["validated_source_checkpoint_ids"],
        "estimand": metrics["estimand"],
        "principal_test_metrics": metrics,
        "calibration": calibration,
        "mean_target_calibration_error": _calibration_ece(
            metrics, "hospitalized" if hospitalization_only else "unresolved"
        ),
        "subgroup_assurance": assurance,
        "strict_timestamp_order_sensitivity": {
            "cohort_rows": {name: len(part) for name, part in strict_parts.items()},
            "calibration": strict_calibration,
            "test_metrics": strict_metrics,
        },
        "deployment_realistic_sensitivity": {
            "labels_available_through": str(parts["test"]["registration_date"].min()),
            "training_rows_recensored": int(
                (historical_train["journey_event"] != parts["train"]["journey_event"]).sum()
            ),
            "validation_rows_recensored": int(
                (historical_validation["journey_event"] != parts["validation"]["journey_event"]).sum()
            ),
            "calibration": "not refit because late-fold labels lack full 30-day observability",
            "test_metrics_uncalibrated": historical_metrics,
        },
        "model": model_info,
        "runtime_seconds": time.time() - started,
        "resources": {
            "model_threads": resources.model_threads,
            "execution": "sequential_finalists",
            "process_peak_rss_bytes_before": peak_before,
            "process_peak_rss_bytes_at_completion": _peak_rss_bytes(),
        },
    }
    return result, model_object


def _future_serving_contract() -> dict:
    return {
        "status": "draft_only_not_implemented",
        "candidate_independent": True,
        "backend_api_changed": False,
        "fields": {
            "hospitalization_probability_7d": "number[0,1]",
            "hospitalization_probability_14d": "number[0,1]",
            "hospitalization_probability_30d": "number[0,1]",
            "refusal_probability_7d_14d_30d": "optional; only for a competing-risk estimand",
            "unresolved_probability_7d_14d_30d": "number[0,1] per horizon",
            "model_version": "string",
            "calibration_version": "string",
            "support_confidence_metadata": "object",
            "prediction_timestamp": "RFC3339 timestamp",
            "data_freshness_metadata": "object",
        },
        "prohibited": ["xgboost-specific fields", "lightgbm-specific fields"],
    }


def _compact_confirmation_result(result: dict) -> dict:
    metrics = result["principal_test_metrics"]
    return {
        "candidate": result["candidate"],
        "fold": result["fold"],
        "source_trial": result["source_trial"],
        "frozen_parameters": result["frozen_parameters"],
        "parameter_source_checkpoint_ids": result["parameter_source_checkpoint_ids"],
        "estimand": result["estimand"],
        "principal": {
            "primary_metric_name": metrics["primary_metric_name"],
            "mean_matching_horizon_brier": metrics["primary_metric"],
            "brier_by_horizon": {
                horizon: {
                    "hospitalized": row["brier_hospitalized"],
                    "refused": row["brier_refused"],
                    "multiclass": row["brier_multiclass"],
                }
                for horizon, row in metrics["by_horizon"].items()
            },
            "concordance": metrics["concordance"],
            "mean_target_calibration_error": result["mean_target_calibration_error"],
        },
        "calibration": {
            horizon: {
                "selected": row["selected"],
                "fit_rows": row.get("fit_rows"),
                "selection_rows": row.get("selection_rows"),
                "selection_brier": row.get("selection_brier"),
                "parameter_kind": row["parameters"]["method"],
                "parameter_count": (
                    len(row["parameters"].get("x_thresholds", []))
                    if row["parameters"]["method"] == "isotonic"
                    else len(row["parameters"]) - 1
                ),
            }
            for horizon, row in result["calibration"].items()
        },
        "regional_assurance": {
            "supported_regions": len(result["subgroup_assurance"]["supported_regions"]),
            "low_support_regions": len(result["subgroup_assurance"]["low_support_regions"]),
            "median_supported_region_brier": result["subgroup_assurance"]["median_region_brier"],
            "worst_supported_region_brier": result["subgroup_assurance"]["worst_region_brier"],
            "regions_losing_baseline": result["subgroup_assurance"]["regions_losing_baseline"],
        },
        "major_profile_assurance": result["subgroup_assurance"]["major_profiles"],
        "strict_timestamp_order_sensitivity": {
            "cohort_rows": result["strict_timestamp_order_sensitivity"]["cohort_rows"],
            "mean_matching_horizon_brier": result["strict_timestamp_order_sensitivity"]["test_metrics"][
                "primary_metric"
            ],
            "concordance": result["strict_timestamp_order_sensitivity"]["test_metrics"]["concordance"],
        },
        "deployment_realistic_sensitivity": {
            "labels_available_through": result["deployment_realistic_sensitivity"]["labels_available_through"],
            "training_rows_recensored": result["deployment_realistic_sensitivity"]["training_rows_recensored"],
            "validation_rows_recensored": result["deployment_realistic_sensitivity"]["validation_rows_recensored"],
            "mean_matching_horizon_brier": result["deployment_realistic_sensitivity"]["test_metrics_uncalibrated"][
                "primary_metric"
            ],
            "concordance": result["deployment_realistic_sensitivity"]["test_metrics_uncalibrated"]["concordance"],
        },
        "runtime_seconds": result["runtime_seconds"],
        "resources": result["resources"],
        "model": result["model"],
        "detailed_calibration_and_assurance": "persisted in the checksummed checkpoint artifact",
    }


def _compact_refusal_result(result: dict) -> dict:
    return {
        key: result[key]
        for key in (
            "candidate",
            "fold",
            "frozen_classifier",
            "estimand",
            "test_metrics",
            "selected_calibration",
            "validation_brier",
            "confirmation_validation_winner",
            "legacy_note",
            "runtime_seconds",
            "resources",
        )
    } | {
        "regional_assurance": {
            "supported_regions": len(result["regional_assurance"]["regions"])
            - len(result["regional_assurance"]["low_support_regions"]),
            "low_support_regions": len(result["regional_assurance"]["low_support_regions"]),
            "median_supported_region_brier": result["regional_assurance"]["median_supported_region_brier"],
            "worst_supported_region_brier": result["regional_assurance"]["worst_supported_region_brier"],
            "worst_region_degradation_vs_national": result["regional_assurance"][
                "worst_region_degradation_vs_national"
            ],
        },
        "detailed_regional_assurance": "persisted in the checksummed checkpoint artifact",
    }


def _confirmation_decision(results):
    final = {row["candidate"]: row for row in results if row["fold"] == "q1_final"}
    aft = final["xgboost_aft"]
    hazard = final["discrete_hospitalization_hazard"]
    comparisons = {
        "principal_mean_brier": {
            "aft": aft["principal_test_metrics"]["primary_metric"],
            "hazard": hazard["principal_test_metrics"]["primary_metric"],
            "lower_is_better": True,
        },
        "strict_mean_brier": {
            "aft": aft["strict_timestamp_order_sensitivity"]["test_metrics"]["primary_metric"],
            "hazard": hazard["strict_timestamp_order_sensitivity"]["test_metrics"]["primary_metric"],
            "lower_is_better": True,
        },
        "deployment_realistic_mean_brier": {
            "aft": aft["deployment_realistic_sensitivity"]["test_metrics_uncalibrated"]["primary_metric"],
            "hazard": hazard["deployment_realistic_sensitivity"]["test_metrics_uncalibrated"]["primary_metric"],
            "lower_is_better": True,
        },
        "concordance": {
            "aft": aft["principal_test_metrics"]["concordance"],
            "hazard": hazard["principal_test_metrics"]["concordance"],
            "lower_is_better": False,
        },
        "mean_calibration_error": {
            "aft": aft["mean_target_calibration_error"],
            "hazard": hazard["mean_target_calibration_error"],
            "lower_is_better": True,
        },
        "worst_supported_region_brier": {
            "aft": aft["subgroup_assurance"]["worst_region_brier"],
            "hazard": hazard["subgroup_assurance"]["worst_region_brier"],
            "lower_is_better": True,
        },
        "runtime_seconds": {
            "aft": aft["runtime_seconds"],
            "hazard": hazard["runtime_seconds"],
            "lower_is_better": True,
        },
    }
    winners = {}
    for dimension, row in comparisons.items():
        if row["aft"] == row["hazard"]:
            winners[dimension] = "tie"
        elif row["lower_is_better"]:
            winners[dimension] = "aft" if row["aft"] < row["hazard"] else "hazard"
        else:
            winners[dimension] = "aft" if row["aft"] > row["hazard"] else "hazard"
    non_ties = {winner for winner in winners.values() if winner != "tie"}
    if non_ties == {"aft"}:
        recommendation = "recommend AFT for human promotion review"
    elif non_ties == {"hazard"}:
        recommendation = "recommend hazard for human promotion review"
    else:
        recommendation = "retain both pending product/serving tradeoff"
    return {
        "recommendation": recommendation,
        "automatic_promotion": False,
        "human_review_required": True,
        "selection_rule": "recommend a single model only under cross-dimension dominance; no weighted score",
        "dimension_comparison": comparisons,
        "dimension_winners": winners,
        "competing_risk_decision": "retain empirical baseline; ML competing-risk challenger not retrained",
    }


def run_final_confirmation(*, args, root, settings, config, resources, folds, data, audit, plan, source_evidence):
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import CheckpointKey, ExperimentRun
    from hqai_ml.tournament.candidates import empirical_competing_probabilities
    from hqai_ml.tournament.labels import split_by_period
    from hqai_ml.tournament.refusal import refusal_benchmarks

    confirmation_started = time.time()
    run = None
    checkpoint_keys = []
    checkpoint_parameters = {}
    reused = 0
    results = []
    refusal_result = None
    current_manifest = settings.artifacts_dir / "models" / store.MANIFEST
    manifest_sha_before = store.sha256_file(current_manifest) if current_manifest.exists() else None
    try:
        run = ExperimentRun.start(settings.artifacts_dir, plan, run_id=args.run_id, resume_run_id=args.resume)
        run_id = run.manifest["run_id"]
        evidence_path = settings.artifacts_dir / "tournaments" / run_id / "final-evidence.json"
        prior_evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else None
        log(f"full-cohort confirmation run: {run_id}; eligible rows: {len(data):,}")
        fold_parts = {}
        for fold in folds:
            parts = {
                name: split_by_period(data, getattr(fold, name))
                for name in ("train", "validation", "calibration", "test")
            }
            parts["fold_id"] = fold.id
            fold_parts[fold.id] = parts
            log(
                f"fold {fold.id}: "
                + ", ".join(f"{name}={len(parts[name]):,}" for name in ("train", "validation", "calibration", "test"))
            )

        baselines = {
            fold.id: empirical_competing_probabilities(
                fold_parts[fold.id]["train"],
                fold_parts[fold.id]["test"],
                config.horizons,
                config.group_baseline.columns,
                config.group_baseline.min_support,
            )
            for fold in folds
        }
        for candidate, selection in source_evidence["finalists"].items():
            for fold in folds:
                key = CheckpointKey(
                    "patient_journey", f"{candidate}-final-confirmation", selection["trial_id"], fold.id
                )
                parameters = {
                    "source_run": args.source_run,
                    "source_trial": selection["trial_id"],
                    "frozen_parameters": selection["parameters"],
                }
                checkpoint_keys.append(key)
                checkpoint_parameters[key.identifier] = parameters
                existing = run.reusable_checkpoint(key, parameters=parameters)
                if existing:
                    reused += 1
                    results.append(load_result_artifact(settings.artifacts_dir, existing))
                    continue
                run.start_checkpoint(key, parameters=parameters)
                try:
                    result, model = _evaluate_frozen_candidate(
                        candidate,
                        fold_parts[fold.id],
                        baselines[fold.id],
                        selection,
                        config,
                        resources,
                        settings.artifacts_dir,
                        config.profiles["overnight"].round_cap,
                    )
                    artifact_path, artifact_sha = write_result_artifact(
                        settings.artifacts_dir, run_id, key, result, model
                    )
                    run.complete_checkpoint(
                        key,
                        parameters=parameters,
                        metrics={
                            "test_primary_metric": result["principal_test_metrics"]["primary_metric"],
                            "primary_metric_name": result["principal_test_metrics"]["primary_metric_name"],
                            "estimand": result["estimand"],
                        },
                        artifact_path=artifact_path,
                        artifact_sha256=artifact_sha,
                        version=f"{candidate}-{fold.id}-full-confirmation",
                        evaluation_status="completed",
                    )
                    results.append(result)
                    log(f"confirmed {candidate}/{fold.id}: {result['principal_test_metrics']['primary_metric']:.6f}")
                except KeyboardInterrupt:
                    run.interrupt_checkpoint(key)
                    raise
                except BaseException as exc:
                    run.fail_checkpoint(key, exc, root)
                    raise

        final_fold = folds[-1]
        refusal_key = CheckpointKey(
            "patient_journey",
            "refusal-final-confirmation",
            source_evidence["refusal_classifier"],
            final_fold.id,
        )
        refusal_parameters = {
            "source_run": args.source_run,
            "frozen_classifier": source_evidence["refusal_classifier"],
            "policy": config.refusal_benchmarks,
        }
        checkpoint_keys.append(refusal_key)
        checkpoint_parameters[refusal_key.identifier] = refusal_parameters
        existing = run.reusable_checkpoint(refusal_key, parameters=refusal_parameters)
        if existing:
            reused += 1
            refusal_result = load_result_artifact(settings.artifacts_dir, existing)
        else:
            run.start_checkpoint(refusal_key, parameters=refusal_parameters)
            try:
                started = time.time()
                parts = fold_parts[final_fold.id]
                _, legacy_reason = legacy_fold_eligibility(
                    "legacy_refusal_risk", final_fold, config.legacy_artifacts_trained_through
                )
                benchmark = refusal_benchmarks(
                    *[parts[name] for name in ("train", "validation", "calibration", "test")],
                    settings.artifacts_dir,
                    config.refusal_benchmarks,
                    resources.model_threads,
                    config.support_buckets[0],
                    legacy_eligible=False,
                    legacy_ineligibility_reason=legacy_reason,
                    forced_selected_classifier=source_evidence["refusal_classifier"],
                )
                selected_calibration = benchmark["selected_calibration"]["method"]
                refusal_result = {
                    "candidate": "refusal_classifier",
                    "fold": final_fold.id,
                    "frozen_classifier": source_evidence["refusal_classifier"],
                    "estimand": benchmark["estimand"],
                    "test_metrics": benchmark["calibration"][selected_calibration],
                    "selected_calibration": benchmark["selected_calibration"],
                    "regional_assurance": benchmark["regional_assurance"],
                    "validation_brier": benchmark["validation_brier"],
                    "confirmation_validation_winner": benchmark["confirmation_validation_winner"],
                    "legacy_note": benchmark["legacy_note"],
                    "runtime_seconds": time.time() - started,
                    "resources": {
                        "model_threads": resources.model_threads,
                        "execution": "sequential_finalists",
                        "process_peak_rss_bytes_at_completion": _peak_rss_bytes(),
                    },
                }
                artifact_path, artifact_sha = write_result_artifact(
                    settings.artifacts_dir, run_id, refusal_key, refusal_result, None
                )
                run.complete_checkpoint(
                    refusal_key,
                    parameters=refusal_parameters,
                    metrics={"test_metrics": refusal_result["test_metrics"], "estimand": refusal_result["estimand"]},
                    artifact_path=artifact_path,
                    artifact_sha256=artifact_sha,
                    version=f"refusal-{final_fold.id}-full-confirmation",
                    evaluation_status="completed",
                )
            except KeyboardInterrupt:
                run.interrupt_checkpoint(refusal_key)
                raise
            except BaseException as exc:
                run.fail_checkpoint(refusal_key, exc, root)
                raise

        decision = _confirmation_decision(results)
        manifest_sha_after = store.sha256_file(current_manifest) if current_manifest.exists() else None
        initial_wall_runtime = (
            prior_evidence["initial_wall_runtime_seconds"]
            if prior_evidence is not None
            else time.time() - confirmation_started
        )
        cohort_audit_path = settings.artifacts_dir / "tournaments" / run_id / "cohort-audit.json"
        store.atomic_write_text(cohort_audit_path, store.canonical_json(audit))
        evidence = {
            "schema_version": 1,
            "mode": "full_cohort_final_confirmation",
            "run_id": run_id,
            "source_tournament": {
                key: value for key, value in source_evidence.items() if key not in {"source_summary_path"}
            },
            "full_cohort_rows": len(data),
            "event_audit": {key: value for key, value in audit.items() if key != "cohort_by_dimension"},
            "cohort_dimension_audit": cohort_audit_path.relative_to(settings.artifacts_dir).as_posix(),
            "fold_rows": {
                fold.id: {
                    name: len(fold_parts[fold.id][name]) for name in ("train", "validation", "calibration", "test")
                }
                for fold in folds
            },
            "results": [_compact_confirmation_result(result) for result in results],
            "refusal_result": _compact_refusal_result(refusal_result),
            "negative_control": {
                "discrete_competing_risk": "not retrained; source tournament showed it underperformed empirical"
            },
            "decision": decision,
            "serving_contract_draft": _future_serving_contract(),
            "resources": {
                **plan["execution"]["resources"],
                "execution": "sequential_finalists",
                "observed_process_peak_rss_bytes": _peak_rss_bytes(),
            },
            "initial_wall_runtime_seconds": initial_wall_runtime,
            "summed_checkpoint_runtime_seconds": sum(row["runtime_seconds"] for row in results)
            + refusal_result["runtime_seconds"],
            "reused_checkpoints": reused,
            "automatic_promotion": False,
            "human_review_required": True,
            "current_manifest_sha256_before": manifest_sha_before,
            "current_manifest_sha256_after": manifest_sha_after,
            "current_manifest_changed": manifest_sha_before != manifest_sha_after,
        }
        store.atomic_write_text(evidence_path, store.canonical_json(evidence))
        store.atomic_write_text(
            settings.artifacts_dir / "tournaments" / run_id / "champion-decision.json",
            store.canonical_json(decision),
        )
        if run.manifest["status"] != "completed":
            run.complete(checkpoint_keys, parameters_by_key=checkpoint_parameters)
        log(f"final evidence: {evidence_path.relative_to(root)}; reused checkpoints: {reused}")
        print(f"CONFIRMATION_RUN_ID={run_id}")
        return 0
    except KeyboardInterrupt:
        if run is not None:
            run.pause()
        raise
    except BaseException as exc:
        if run is not None:
            run.fail(exc, root)
        raise
    finally:
        if run is not None:
            run.release_lock()


def fit_and_predict(
    candidate,
    train,
    calibration,
    test,
    parameters,
    config,
    resources,
    artifacts_dir,
    round_cap,
    *,
    validation=None,
):
    from hqai_ml.tournament.candidates import (
        empirical_competing_probabilities,
        fit_aft,
        fit_hazard,
        legacy_wait_probabilities,
    )

    fit_validation = validation if validation is not None else calibration
    if candidate == "empirical_competing_risk":
        cal = empirical_competing_probabilities(
            train, calibration, config.horizons, config.group_baseline.columns, config.group_baseline.min_support
        )
        target = (
            cal
            if test is None
            else empirical_competing_probabilities(
                train, test, config.horizons, config.group_baseline.columns, config.group_baseline.min_support
            )
        )
        return cal, target, {"family": "Aalen-Johansen empirical competing-risk baseline"}
    if candidate == "legacy_wait_regression":
        cal, _ = legacy_wait_probabilities(artifacts_dir, calibration, config.horizons)
        target = cal if test is None else legacy_wait_probabilities(artifacts_dir, test, config.horizons)[0]
        return cal, target, {"family": "legacy exact wait regression thresholded by horizon"}
    if candidate == "xgboost_aft":
        model = fit_aft(train, fit_validation, parameters, threads=resources.model_threads, round_cap=round_cap)
    elif candidate == "discrete_hospitalization_hazard":
        model = fit_hazard(
            train,
            fit_validation,
            parameters,
            config.time_bins,
            competing=False,
            threads=resources.model_threads,
            round_cap=round_cap,
        )
    elif candidate == "discrete_competing_risk":
        model = fit_hazard(
            train,
            fit_validation,
            parameters,
            config.time_bins,
            competing=True,
            threads=resources.model_threads,
            round_cap=round_cap,
        )
    else:
        raise ValueError(f"unknown candidate {candidate!r}")
    cal = model.probabilities(calibration, config.horizons)
    target = cal if test is None else model.probabilities(test, config.horizons)
    from hqai_ml.tournament.candidates import FEATURES

    if candidate == "xgboost_aft":
        gains = model.booster.get_score(importance_type="gain")

        def feature_name(name):
            return FEATURES[int(name.removeprefix("f"))] if name.startswith("f") and name[1:].isdigit() else name

        importance = sorted(
            ({"feature": feature_name(name), "gain": float(gain)} for name, gain in gains.items()),
            key=lambda row: row["gain"],
            reverse=True,
        )[:20]
    else:
        importance = sorted(
            (
                {"feature": feature, "gain": float(gain)}
                for feature, gain in zip(
                    [*FEATURES, "time_interval"], model.booster.feature_importance("gain"), strict=True
                )
            ),
            key=lambda row: row["gain"],
            reverse=True,
        )[:20]
    return (
        cal,
        target,
        {
            "family": type(model).__name__,
            "best_iteration": model.best_iteration,
            "operational_feature_importance": importance,
            "explanation_note": "associations with near-term event probability; not causal effects",
            "model_object": model,
        },
    )


def candidate_limitations(candidate: str) -> list[str]:
    common = ["Q1 2025 registrations only", "associations are not causal", "no clinical or routing decision"]
    specific = {
        "empirical_competing_risk": ["group estimates fall back to national curve below support threshold"],
        "legacy_wait_regression": ["completed hospitalized subset only; does not model censoring"],
        "xgboost_aft": ["refusal is treated as right-censoring for the hospitalization estimand"],
        "discrete_hospitalization_hazard": ["refusal is a competing censor, not a predicted cause"],
        "discrete_competing_risk": ["discrete interval hazards approximate within-bin event timing"],
    }
    return [*common, *specific[candidate]]


def candidate_estimand(candidate: str) -> str:
    if candidate in {"legacy_wait_regression", "xgboost_aft", "discrete_hospitalization_hazard"}:
        return "cumulative incidence of hospitalization by each emitted horizon; refusal treated as competing censoring"
    return "three-state distribution of hospitalized, refused, or unresolved by each emitted horizon"


def legacy_fold_eligibility(candidate, fold, trained_through):
    if candidate not in {"legacy_wait_regression", "legacy_refusal_risk"}:
        return True, None
    overlaps = [name for name in ("validation", "calibration", "test") if getattr(fold, name)[0] <= trained_through]
    if not overlaps:
        return True, None
    return (
        False,
        f"legacy artifact trained through {trained_through.isoformat()}; fold {fold.id} "
        f"{', '.join(overlaps)} overlaps its training window, so in-sample metrics are excluded",
    )


def select_cross_fold_trial(trials: list[dict]) -> dict:
    """Select one parameter set on aggregate validation performance, with stable tie-breaking."""
    if not trials:
        raise ValueError("at least one compatible trial is required")
    return min(trials, key=lambda row: (row["mean_validation_primary_metric"], row["trial_id"]))


def write_result_artifact(artifacts_dir, run_id, key, result, model):
    from hqai_ml.registry import store

    path = artifacts_dir / "tournaments" / run_id / key.filename.removesuffix(".json")
    if path.exists():
        manifest = store.verify_artifact_manifest(path, adopt_legacy=False)
        return path, manifest["content_sha256"]
    temporary = path.with_name(f".{path.name}.partial-{os.getpid()}")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    store.atomic_write_text(temporary / "metrics.json", store.canonical_json(result))
    store.atomic_write_text(
        temporary / "meta.json",
        store.canonical_json(
            {
                "model_name": "patient_journey",
                "candidate": result["candidate"],
                "fold": result["fold"],
                "evaluation_status": "completed",
            }
        ),
    )
    if model is not None:
        if hasattr(model, "booster") and model.__class__.__name__ == "AFTModel":
            model.booster.save_model(temporary / "model.json")
        elif hasattr(model, "booster"):
            model.booster.save_model(temporary / "model.txt")
        store.atomic_write_text(temporary / "categories.json", store.canonical_json(model.encoder.categories))
    store.write_artifact_manifest(temporary)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.rmtree(temporary)
        raise FileExistsError(path)
    os.replace(temporary, path)
    manifest = store.verify_artifact_manifest(path, adopt_legacy=False)
    return path, manifest["content_sha256"]


def load_result_artifact(artifacts_dir, checkpoint):
    path = artifacts_dir / checkpoint["artifact"]["path"]
    return json.loads((path / "metrics.json").read_text(encoding="utf-8"))


def tournament_summary(
    config,
    profile,
    run_id,
    audit,
    sampled_rows,
    results,
    refusal,
    reused,
    exclusions,
    selections,
    manifest_sha_before,
    manifest_sha_after,
):
    eligibility = []
    for result in results:
        coherent = all(row["coherence_max_abs_error"] <= 1e-6 for row in result["test_metrics"]["by_horizon"].values())
        eligibility.append(
            {
                "candidate": result["candidate"],
                "fold": result["fold"],
                "status": "evaluated",
                "estimand": result["estimand"],
                "primary_metric_name": result["primary_metric_name"],
                "valid_probabilities": coherent,
                "calibration_artifact": bool(result["calibration"]),
                "regional_assurance": bool(result["subgroup_assurance"]["regions"]),
                "human_review_required": True,
            }
        )
    eligibility.extend(
        {
            **row,
            "primary_metric_name": (
                "mean_hospitalization_brier_at_emitted_horizons"
                if row["candidate"] == "legacy_wait_regression"
                else "not_evaluated"
            ),
            "human_review_required": True,
        }
        for row in exclusions
    )
    return {
        "schema_version": 1,
        "run_id": run_id,
        "profile": profile,
        "config_identity": config.identity_sha256,
        "event_audit": audit,
        "sampled_rows": sampled_rows,
        "results": results,
        "candidate_exclusions": exclusions,
        "cross_fold_selections": selections,
        "refusal_benchmarks": refusal,
        "reused_checkpoints": reused,
        "champion_decision": {
            "automatic_promotion": False,
            "recommendation": "human_review_required",
            "default_outcome": config.promotion_constraints.outcome_if_not_clearly_superior,
            "eligibility": eligibility,
            "current_manifest_sha256_before": manifest_sha_before,
            "current_manifest_sha256_after": manifest_sha_after,
            "current_manifest_changed": manifest_sha_before != manifest_sha_after,
        },
    }


if __name__ == "__main__":
    sys.exit(main())
