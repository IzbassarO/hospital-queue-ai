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
    args = parser.parse_args()

    resources = resource_config(args.profile)
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
    if profile.sample_rows is not None and len(data) > profile.sample_rows:
        data = data.sample(profile.sample_rows, random_state=config.seed).sort_values(
            ["registration_date", "referral_id"]
        )
        data = data.reset_index(drop=True)
    protocol = {
        "label_cutoff": config.label_contract.cutoff.isoformat(),
        "horizons": config.horizons,
        "folds": [fold.model_dump(mode="json") for fold in folds],
        "split_order": ["train", "validation", "calibration", "test"],
        "final_test_used_for_hpo": False,
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
                }
            ),
            end="",
        )
        return 0

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
