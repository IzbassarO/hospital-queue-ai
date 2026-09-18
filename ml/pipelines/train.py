#!/usr/bin/env python3
"""Train and evaluate model candidates; explicitly promote them with ``--promote``.

Run:  make train                                   (all three models)
      PYTHONPATH=ml .venv/bin/python ml/pipelines/train.py --model wait_time|refusal_risk|load_forecast
Reads data/processed/*.parquet only (no Postgres).
"""

import argparse
import sys
import time
import warnings
from pathlib import Path

from hqai_ml.registry.resources import apply_resource_environment, resource_config

T0 = time.time()
MODEL_NAMES = ("wait_time", "refusal_risk", "load_forecast")


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def compare_with_current(settings, name: str, new_metrics: dict, new_holidays: list[str]) -> dict | None:
    """Pooled WAPE of the version about to be replaced vs the new run, copied into the new metrics.json
    so the change stays traceable after old versions are deleted."""
    from hqai_ml.registry import store

    try:
        old = store.load(settings.artifacts_dir, name)
    except FileNotFoundError:
        return None
    old_holidays = old["meta"].get("holidays")
    if old_holidays is None:  # versions trained before the holiday list was stored in meta.json
        flagged = {c["date"] for c in old["metrics"].get("calendar_check", []) if c["holiday_flag"]}
        unflagged = {c["date"] for c in old["metrics"].get("calendar_check", []) if not c["holiday_flag"]}
        added = sorted(d for d in new_holidays if d in unflagged)
        removed = sorted(d for d in flagged if d not in new_holidays)
    else:
        added = sorted(set(new_holidays) - set(old_holidays))
        removed = sorted(set(old_holidays) - set(new_holidays))
    before = {(r["target"], r["eval_level"]): r for r in old["metrics"]["pooled"]}
    rows = [
        {
            "target": r["target"],
            "eval_level": r["eval_level"],
            "wape_model_before": before.get((r["target"], r["eval_level"]), {}).get("wape_model"),
            "wape_model_after": r["wape_model"],
            "wape_seasonal_naive": r["wape_seasonal_naive"],
        }
        for r in new_metrics["pooled"]
    ]
    return {"previous_version": old["version"], "holidays_added": added, "holidays_removed": removed, "pooled": rows}


def metric_summary(name: str, metrics: dict) -> tuple[dict, dict]:
    if name in ("wait_time", "refusal_risk"):
        model = next(row for row in metrics["overall"] if row["model"] == "LightGBM")
        baselines = [row for row in metrics["overall"] if row["model"] != "LightGBM"]
        return model, {row["model"]: row for row in baselines}
    model = {"beats_seasonal_naive": metrics["beats_seasonal_naive"], "pooled": metrics["pooled"]}
    baselines = {
        baseline: [
            {key: value for key, value in row.items() if baseline in key or key in {"target", "eval_level"}}
            for row in metrics["pooled"]
        ]
        for baseline in ("seasonal_naive", "mean_28d", "mean_7d")
    }
    return model, baselines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=["all", *MODEL_NAMES], default="all")
    ap.add_argument("--run-id", help="explicit new run identifier (otherwise timestamp + identity hash)")
    ap.add_argument("--resume", metavar="RUN_ID", help="resume a compatible interrupted run")
    ap.add_argument("--resource-profile", choices=("smoke", "laptop", "overnight"), default="laptop")
    ap.add_argument("--model-threads", type=int, help="override model/BLAS thread limit")
    ap.add_argument("--parallel-trials", type=int, help="override bounded future tournament concurrency")
    ap.add_argument("--process-concurrency", type=int, help="override bounded worker-process concurrency")
    ap.add_argument("--duckdb-memory-mb", type=int, help="override per-session DuckDB memory within profile budget")
    ap.add_argument("--plan", action="store_true", help="show identities, output and checkpoint reuse without training")
    ap.add_argument(
        "--promote",
        action="store_true",
        help="explicitly publish the completed selected model set as current",
    )
    ap.add_argument(
        "--recover-stale-lock",
        metavar="RUN_ID",
        help="explicitly remove a diagnosed stale local run lock, then exit",
    )
    ap.add_argument("--confirm-lock-id", help="exact on-disk lock ID required for stale-lock recovery")
    ap.add_argument(
        "--force-remote-lock-recovery",
        action="store_true",
        help="explicitly recover a confirmed lock from another/unknown host",
    )
    args = ap.parse_args()
    if args.recover_stale_lock and not args.confirm_lock_id:
        ap.error("--recover-stale-lock requires --confirm-lock-id")
    if (args.confirm_lock_id or args.force_remote_lock_recovery) and not args.recover_stale_lock:
        ap.error("lock recovery confirmation options require --recover-stale-lock")
    selected = list(MODEL_NAMES) if args.model == "all" else [args.model]
    resources = resource_config(
        args.resource_profile,
        model_threads=args.model_threads,
        parallel_trials=args.parallel_trials,
        process_concurrency=args.process_concurrency,
        duckdb_memory_mb=args.duckdb_memory_mb,
    )
    apply_resource_environment(resources)

    from hqai_ml.evaluation.protocol import protocols_for
    from hqai_ml.evaluation.report import write_report
    from hqai_ml.features.data import connect, display_lookups
    from hqai_ml.features.load import load_panels
    from hqai_ml.features.referral import build_referral_features
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.models import load_forecast, refusal_risk, wait_time
    from hqai_ml.models.config import load_model_config
    from hqai_ml.registry import store
    from hqai_ml.registry.experiment import (
        CheckpointIncompatibleError,
        CheckpointKey,
        ExperimentRun,
        RunLock,
        build_plan,
    )
    from hqai_ml.registry.resources import seed_process

    models = {"wait_time": wait_time, "refusal_risk": refusal_risk, "load_forecast": load_forecast}
    warnings.filterwarnings("ignore", category=UserWarning)

    settings = IngestSettings()
    if args.recover_stale_lock:
        recovered = RunLock.recover(
            settings.artifacts_dir / "runs" / args.recover_stale_lock,
            confirm_lock_id=args.confirm_lock_id,
            force_remote=args.force_remote_lock_recovery,
        )
        print(f"removed stale lock for {args.recover_stale_lock!r}: {store.canonical_json(recovered)}", end="")
        return 0
    cards = store.load_cards(settings.configs_dir)
    cfg = load_model_config(settings)
    cfg.lightgbm = {**cfg.lightgbm, "num_threads": resources.model_threads}
    seed_process(int(cfg.lightgbm["seed"]))
    root = Path(__file__).resolve().parents[2]
    temporal_protocols = protocols_for(selected, cfg)
    plan = build_plan(
        root=root,
        processed_dir=settings.processed_dir,
        configs_dir=settings.configs_dir,
        selected_models=selected,
        resources=resources,
        temporal_protocols=temporal_protocols,
        hyperparameters=cfg.model_dump(mode="json"),
    )
    if args.plan:
        reuse = dict.fromkeys(selected, False)
        if args.resume:
            inspection = ExperimentRun.read_only(settings.artifacts_dir, args.resume)
            if inspection.manifest["scientific_identity_sha256"] != plan["scientific_identity_sha256"]:
                if inspection.manifest.get("implementation_versions") != plan.get("implementation_versions"):
                    raise CheckpointIncompatibleError(
                        "resume rejected: scientifically relevant implementation versions changed"
                    )
                raise CheckpointIncompatibleError("resume rejected: current scientific plan is incompatible")
            reuse = {name: inspection.reusable_checkpoint(CheckpointKey.model(name)) is not None for name in selected}
        print(
            store.canonical_json(
                {
                    "scientific_identity_sha256": plan["scientific_identity_sha256"],
                    "models": selected,
                    "dataset_identity": plan["dataset"]["identity_sha256"],
                    "config_identity": plan["configuration"]["sha256"],
                    "code_identity": plan["code"]["source"]["sha256"],
                    "checkpoint_root": f"artifacts/runs/{args.resume or '<run-id>'}/checkpoints",
                    "resume_run_id": args.resume,
                    "checkpoint_reuse": reuse,
                    "promotion_requested": args.promote,
                    "execution": plan["execution"],
                }
            ),
            end="",
        )
        return 0

    run = None
    try:
        run = ExperimentRun.start(settings.artifacts_dir, plan, run_id=args.run_id, resume_run_id=args.resume)
        log(f"run: {run.manifest['run_id']} ({run.path.relative_to(root)})")
        keys = {name: CheckpointKey.model(name) for name in selected}
        reusable = {}
        for name in selected:
            checkpoint = run.reusable_checkpoint(keys[name])
            reusable[name] = checkpoint
            if checkpoint:
                log(f"  reuse {name} {checkpoint['artifact']['version']} (checksum verified)")
        pending = [name for name in selected if not reusable[name]]
        if not pending:
            if run.manifest["status"] != "completed":
                run.complete(list(keys.values()))
            if args.promote:
                store.set_current_many(
                    settings.artifacts_dir,
                    {name: reusable[name]["artifact"]["version"] for name in selected},
                )
                report = write_report(settings, cfg)
                log(f"promoted current set; report: {report}")
            else:
                log("completed candidates retained without promotion (use --promote for explicit publication)")
            return 0

        con = connect(settings.processed_dir, resources)
        split = cfg.split.model_dump(mode="json")
        lineage = {
            "run_id": run.manifest["run_id"],
            "dataset_identity": plan["dataset"]["identity_sha256"],
            "config_identity": plan["configuration"]["sha256"],
            "code_identity": plan["code"]["source"]["sha256"],
            "evaluation_status": "completed",
            "resource_config": run.current_execution["resources"],
            "random_seeds": plan["random_seeds"],
            "implementation_versions": plan["implementation_versions"],
        }

        referral_models = [name for name in pending if name in ("wait_time", "refusal_risk")]
        if referral_models:
            df = build_referral_features(con, cfg.split.train_start)
            display = display_lookups(con)
            log(f"referral features: {len(df):,} rows")
            for name in referral_models:
                key = keys[name]
                run.start_checkpoint(key)
                log(f"training {name} …")
                try:
                    res = models[name].train_and_evaluate(df, cfg, display)
                    model = res["model"]
                    meta = {
                        **lineage,
                        "checkpoint_file": key.filename,
                        "temporal_protocol": temporal_protocols[name],
                        "training_window": {
                            "train": [split["train_start"], split["train_end"]],
                            "test": [split["test_start"], split["test_end"]],
                            "date_column": "registration_date",
                            "early_stopping_holdout_days": cfg.early_stopping.holdout_days,
                        },
                        "population": res["metrics"]["population"],
                        "target": "log1p(wait_days)" if name == "wait_time" else "outcome == refused",
                        "prediction_targets": plan["prediction_targets"][name],
                        "model_family": plan["model_families"][name],
                        "best_iteration": res["best_iteration"],
                        "lightgbm_params": {**cfg.lightgbm, **models[name].OBJECTIVE},
                    }
                    version, path = store.save(
                        settings.artifacts_dir,
                        name,
                        {"model.txt": model.booster},
                        features=model.features,
                        categories=model.categories,
                        meta=meta,
                        metrics=res["metrics"],
                        extra={"display.json": display, "card.json": cards.get(name, {})},
                        make_current=False,
                    )
                    artifact = store.verify_artifact_manifest(path, adopt_legacy=False)
                    model_metrics, baselines = metric_summary(name, res["metrics"])
                    run.complete_checkpoint(
                        key,
                        artifact_path=path,
                        artifact_sha256=artifact["content_sha256"],
                        version=version,
                        metrics=model_metrics,
                        baseline_metrics=baselines,
                        evaluation_status="completed",
                    )
                except KeyboardInterrupt:
                    run.interrupt_checkpoint(key)
                    raise
                except BaseException as exc:
                    run.fail_checkpoint(key, exc, root)
                    raise
                log(f"  saved {name} {version} -> {path.relative_to(settings.artifacts_dir.parent)}")

        if "load_forecast" in pending:
            name = "load_forecast"
            key = keys[name]
            run.start_checkpoint(key)
            log("training load_forecast (rolling-origin backtest + final fit) …")
            try:
                hospital, region = load_panels(con)
                res = load_forecast.train_and_evaluate(hospital, region, cfg, log=log)
                lf = cfg.load_forecast
                meta = {
                    **lineage,
                    "checkpoint_file": key.filename,
                    "temporal_protocol": temporal_protocols[name],
                    "training_window": {
                        "series_selection": [split["train_start"], split["train_end"]],
                        "backtest_origins": [str(origin) for origin in lf.backtest_origins],
                        "final_model_data_through": str(lf.forecast_origin),
                    },
                    "targets": load_forecast.TARGETS,
                    "prediction_targets": plan["prediction_targets"][name],
                    "model_family": plan["model_families"][name],
                    "holidays": [str(day) for day in lf.holidays],
                    "lightgbm_params": {**load_forecast.lgb_params(cfg), "num_boost_round": lf.rounds},
                }
                comparison = compare_with_current(settings, name, res["metrics"], meta["holidays"])
                if comparison:
                    res["metrics"]["previous_version_comparison"] = comparison
                boosters = {f"model_{target}.txt": booster for target, booster in res["boosters"].items()}
                version, path = store.save(
                    settings.artifacts_dir,
                    name,
                    boosters,
                    features=load_forecast._features(cfg),
                    categories=res["categories"],
                    meta=meta,
                    metrics=res["metrics"],
                    extra={"series.json": res["series"], "card.json": cards.get(name, {})},
                    make_current=False,
                )
                artifact = store.verify_artifact_manifest(path, adopt_legacy=False)
                model_metrics, baselines = metric_summary(name, res["metrics"])
                run.complete_checkpoint(
                    key,
                    artifact_path=path,
                    artifact_sha256=artifact["content_sha256"],
                    version=version,
                    metrics=model_metrics,
                    baseline_metrics=baselines,
                    evaluation_status="completed",
                )
            except KeyboardInterrupt:
                run.interrupt_checkpoint(key)
                raise
            except BaseException as exc:
                run.fail_checkpoint(key, exc, root)
                raise
            log(f"  saved {name} {version} -> {path.relative_to(settings.artifacts_dir.parent)}")

        run.complete(list(keys.values()))
        promoted = {}
        for name in selected:
            checkpoint = run.reusable_checkpoint(keys[name])
            assert checkpoint is not None
            promoted[name] = checkpoint["artifact"]["version"]
        if args.promote:
            store.set_current_many(settings.artifacts_dir, promoted)
            report = write_report(settings, cfg)
            log(f"promoted current set; report: {report}")
        else:
            log("completed candidates retained without promotion (use --promote for explicit publication)")
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


if __name__ == "__main__":
    sys.exit(main())
