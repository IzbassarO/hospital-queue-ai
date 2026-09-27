#!/usr/bin/env python3
"""Build models/, the released self-contained copies of the frozen models, from the checksummed artifacts/.

Each released folder holds the native model file and its metadata copied byte for byte from the artifact, the
hand-written standalone predict.py and README.md (never touched here), a joblib bundle, and a small real example with
the predictions the repository's own code path produces for it. Nothing is fitted or changed: the script verifies the
artifact checksums, copies, derives loader metadata (features.json / inference.json where the artifact has none),
builds bundles and examples, and writes models/manifest.json with the sha256 of every shipped file and the provenance
of every source. Running it twice yields identical files; the joblib bundles stay identical as long as the lightgbm
and xgboost versions do not change (they embed the boosters' own serialisation).

Run:  make models-export      (PYTHONPATH=ml .venv/bin/python ml/pipelines/export_models.py [--models wait_time ...])
Reads artifacts/ and data/processed/*.parquet (DuckDB, for the example rows) only; no Postgres.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from hqai_ml.registry.resources import apply_resource_environment, resource_config

T0 = time.time()
ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_ROWS = 50
GZIP = {"method": "gzip", "mtime": 0, "compresslevel": 9}
FLOAT_FORMAT = "%.17g"
HAND_WRITTEN = {"predict.py", "README.md"}

# Frozen release: versions are pinned, not discovered, so a retrain cannot silently change the shipped models.
REGISTRY_VERSIONS = {"wait_time": "20260914-1830", "refusal_risk": "20260914-1831", "load_forecast": "20260914-1918"}
TOURNAMENT_RUN = "journey-full-confirmation-6b2a-final-20260917"
# The accepted full-cohort confirmation evaluated each finalist on two folds; the release ships the q1_final fold
# (train 2025-01-01..02-14, validation 02-15..21, calibration 02-22..28, test March 2025), whose test metrics are the
# ones docs/project-evidence-index.md cites (AFT C-index 0.847552, hazard 0.802645). The q1_fold_1 siblings are
# shorter-history fold models kept as evidence only.
JOURNEY = {
    "patient_journey_aft": {
        "candidate": "xgboost_aft",
        "directory": "patient_journey--xgboost_aft-final-confirmation--trial-008--70e6db266e97c959",
        "content_sha256": "9b2b8a9787c029f7488bd19cab4e6cbd7caf8567093f70f7ff9f180d1a86b2f0",
        "native": "model.json",
    },
    "patient_journey_hazard": {
        "candidate": "discrete_hospitalization_hazard",
        "directory": "patient_journey--discrete_hospitalization_hazard-final-confirmation--trial-030--d8872d7434eb1e26",
        "content_sha256": "db678bfa061510655c984746b22425f15cc45c34144469d376fa5bc0865c2012",
        "native": "model.txt",
    },
}
ALL_MODELS = [*REGISTRY_VERSIONS, *JOURNEY]


def log(message: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {message}", flush=True)


def write_csv(frame, path: Path) -> None:
    frame.to_csv(path, index=False, float_format=FLOAT_FORMAT, compression=GZIP)


def copy_files(source: Path, destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for file in sorted(source.iterdir()):
        if file.is_file():
            (destination / file.name).write_bytes(file.read_bytes())
            copied.append(file.name)
    return copied


def write_bundle(path: Path, bundle: dict) -> None:
    import joblib

    joblib.dump(bundle, path, compress=3)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", choices=ALL_MODELS, default=ALL_MODELS)
    parser.add_argument("--out", type=Path, default=ROOT / "models")
    parser.add_argument("--resource-profile", choices=("smoke", "laptop", "overnight"), default="laptop")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    resources = resource_config(args.resource_profile)
    apply_resource_environment(resources)

    import lightgbm as lgb
    import numpy as np
    import pandas as pd
    import xgboost as xgb

    from hqai_ml.features.data import connect
    from hqai_ml.features.load import SERIES_CATEGORICAL, concat, load_panels
    from hqai_ml.features.referral import CATEGORICAL, build_referral_features
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.models import load_forecast, refusal_risk, wait_time
    from hqai_ml.models.config import load_model_config
    from hqai_ml.models.lgbm import encode
    from hqai_ml.models.referral_model import ReferralModel
    from hqai_ml.registry import store
    from hqai_ml.tournament.candidates import FEATURES as JOURNEY_FEATURES
    from hqai_ml.tournament.candidates import AFTModel, CategoricalFrameEncoder, HazardModel
    from hqai_ml.tournament.config import load_tournament_config
    from hqai_ml.tournament.evaluation import ProbabilityCalibrator
    from hqai_ml.tournament.labels import construct_journey_labels, split_by_period

    settings = IngestSettings()
    cfg = load_model_config(settings)
    cards = store.load_cards(settings.configs_dir)
    out_root: Path = args.out
    out_root.mkdir(parents=True, exist_ok=True)
    con = connect(settings.processed_dir, resources)
    manifest_models: dict[str, dict] = {}

    referral_models = [name for name in args.models if name in ("wait_time", "refusal_risk")]
    journey_models = [name for name in args.models if name in JOURNEY]
    features_frame = None
    if referral_models or journey_models:
        log("building referral features (DuckDB over data/processed) …")
        features_frame = build_referral_features(con, cfg.split.train_start)
        log(f"  {len(features_frame):,} referrals")

    # ---- A, B: referral models from the versioned registry
    for name in referral_models:
        version = REGISTRY_VERSIONS[name]
        artifact = store.load(settings.artifacts_dir, name, version)
        model = ReferralModel(
            name=name,
            booster=artifact["boosters"]["model.txt"],
            features=artifact["features"],
            categories=artifact["categories"],
            display=artifact.get("display", {}),
            version=version,
        )
        target = out_root / name
        copied = copy_files(artifact["path"], target)
        if "card.json" not in copied:
            store._dump(target / "card.json", cards.get(name, {}))
        module = wait_time if name == "wait_time" else refusal_risk
        population = module.population(features_frame)
        test = population[
            (population["registration_date"] >= cfg.split.test_start)
            & (population["registration_date"] <= cfg.split.test_end)
        ]
        sample = test.sample(n=EXAMPLE_ROWS, random_state=42).sort_values("referral_id").reset_index(drop=True)
        example = sample[["referral_id", "registration_date", *model.features]]
        write_csv(example, target / "example.csv.gz")
        output = "pred_wait_days" if name == "wait_time" else "pred_refusal_prob"
        expected = pd.DataFrame({"referral_id": sample["referral_id"], output: model.predict(sample)})
        write_csv(expected, target / "example_expected.csv.gz")
        write_bundle(
            target / "bundle.joblib",
            {
                "name": name,
                "version": version,
                "model": model.booster,
                "features": model.features,
                "categories": model.categories,
                "meta": artifact["meta"],
                "sha256_of_native_file": store.sha256_file(target / "model.txt"),
            },
        )
        manifest_models[name] = {
            "algorithm": "LightGBM "
            + ("regression on log1p(wait_days)" if name == "wait_time" else "binary classifier"),
            "native_files": ["model.txt"],
            "source": {
                "artifact_path": artifact["path"].relative_to(ROOT).as_posix(),
                "artifact_sha256": artifact["artifact_sha256"],
                "version": version,
                "trained_at": artifact["meta"]["trained_at"],
                "training_window": artifact["meta"]["training_window"],
                "run_id": artifact["meta"].get("run_id"),
                "lineage": store.registration_evidence(artifact)["lineage"],
                "card_source": "artifact card.json" if "card.json" in copied else "ml/configs/model_cards.yaml",
            },
            "example": {"rows": len(sample), "population": artifact["meta"]["population"]["definition"]},
        }
        log(f"{name} {version}: {len(copied)} artifact files, example {len(sample)} rows")

    # ---- C: load forecast (two boosters, one per target)
    if "load_forecast" in args.models:
        name = "load_forecast"
        version = REGISTRY_VERSIONS[name]
        artifact = store.load(settings.artifacts_dir, name, version)
        boosters = {t: artifact["boosters"][f"model_{t}.txt"] for t in load_forecast.TARGETS}
        target = out_root / name
        copied = copy_files(artifact["path"], target)
        if "card.json" not in copied:
            store._dump(target / "card.json", cards.get(name, {}))
        hospital, region = load_panels(con)
        modelled_ids = set(artifact["series"]["modelled_hospital_series"])
        mask = hospital.meta["series_id"].isin(modelled_ids).to_numpy()
        panel = concat(hospital.subset(mask), region)
        last = panel.index_of(cfg.load_forecast.forecast_origin)
        features = artifact["features"]
        numeric = [f for f in features if f not in SERIES_CATEGORICAL]
        examples, expectations = [], []
        for tgt in load_forecast.TARGETS:
            rows = load_forecast._rows(panel, tgt, [last], cfg, max_target_index=None)
            sample = rows.sample(n=EXAMPLE_ROWS // 2, random_state=42).sort_values(["series_id", "horizon"])
            example = sample[["series_id", *features]].astype(dict.fromkeys(numeric, "float64")).reset_index(drop=True)
            example.insert(0, "target", tgt)
            example.insert(2, "origin_date", str(cfg.load_forecast.forecast_origin))
            example.insert(
                3,
                "target_date",
                [str(cfg.load_forecast.forecast_origin + pd.Timedelta(days=int(h))) for h in sample["horizon"]],
            )
            expected = pd.DataFrame(
                {
                    "target": tgt,
                    "series_id": sample["series_id"].to_numpy(),
                    "horizon": sample["horizon"].to_numpy(),
                    "pred": boosters[tgt].predict(encode(sample, features, artifact["categories"])),
                }
            )
            examples.append(example)
            expectations.append(expected)
        write_csv(pd.concat(examples, ignore_index=True), target / "example.csv.gz")
        write_csv(pd.concat(expectations, ignore_index=True), target / "example_expected.csv.gz")
        write_bundle(
            target / "bundle.joblib",
            {
                "name": name,
                "version": version,
                "model": boosters,
                "features": features,
                "categories": artifact["categories"],
                "meta": artifact["meta"],
                "sha256_of_native_file": {
                    f"model_{t}.txt": store.sha256_file(target / f"model_{t}.txt") for t in boosters
                },
            },
        )
        manifest_models[name] = {
            "algorithm": "two global LightGBM Poisson boosters (registrations, hospitalizations), horizons 1..14",
            "native_files": [f"model_{t}.txt" for t in load_forecast.TARGETS],
            "source": {
                "artifact_path": artifact["path"].relative_to(ROOT).as_posix(),
                "artifact_sha256": artifact["artifact_sha256"],
                "version": version,
                "trained_at": artifact["meta"]["trained_at"],
                "training_window": artifact["meta"]["training_window"],
                "run_id": artifact["meta"].get("run_id"),
                "lineage": store.registration_evidence(artifact)["lineage"],
                "card_source": "artifact card.json" if "card.json" in copied else "ml/configs/model_cards.yaml",
            },
            "example": {
                "rows": EXAMPLE_ROWS,
                "population": f"forecast rows at origin {cfg.load_forecast.forecast_origin}, modelled series",
            },
        }
        log(f"{name} {version}: {len(copied)} artifact files, example {EXAMPLE_ROWS} rows")

    # ---- D1, D2: accepted patient-journey finalists from the full-cohort confirmation
    if journey_models:
        tournament = load_tournament_config(settings.configs_dir / "tournament.yaml")
        evidence = json.loads(
            (settings.artifacts_dir / "tournaments" / TOURNAMENT_RUN / "final-evidence.json").read_text(
                encoding="utf-8"
            )
        )
        final_fold = next(fold for fold in tournament.folds if fold.id == "q1_final")
        event_fields = con.execute(
            """SELECT referral_id, registration_dt, hospitalization_dt, refusal_dt, is_dup_code, outcome_conflict
               FROM fact_referral ORDER BY referral_id"""
        ).df()
        frame = features_frame.merge(event_fields, on="referral_id", how="left", validate="one_to_one")
        labels = construct_journey_labels(frame, tournament.label_contract)
        test = split_by_period(labels.rows, final_fold.test)
        sample = test.sample(n=EXAMPLE_ROWS, random_state=42).sort_values("referral_id").reset_index(drop=True)
        log(f"journey test fold {final_fold.id}: {len(test):,} eligible referrals, example {len(sample)} rows")
    for name in journey_models:
        spec = JOURNEY[name]
        source = settings.artifacts_dir / "tournaments" / TOURNAMENT_RUN / spec["directory"]
        artifact_manifest = store.verify_artifact_manifest(source, adopt_legacy=False)
        if artifact_manifest["content_sha256"] != spec["content_sha256"]:
            raise store.ArtifactIntegrityError(f"{name}: artifact content changed since the release was pinned")
        metrics = store.load_json(source, "metrics.json")
        meta = store.load_json(source, "meta.json")
        categories = store.load_json(source, "categories.json")
        if meta["candidate"] != spec["candidate"] or meta["fold"] != "q1_final":
            raise store.ArtifactIntegrityError(f"{name}: unexpected candidate/fold {meta}")
        result = next(
            r for r in evidence["results"] if r["candidate"] == spec["candidate"] and r["fold"] == meta["fold"]
        )
        target = out_root / name
        copied = copy_files(source, target)
        store._dump(target / "features.json", {"features": JOURNEY_FEATURES, "categorical": CATEGORICAL})
        calibration = {h: c["parameters"] for h, c in metrics["calibration"].items()}
        inference = {
            "estimand": metrics["estimand"],
            "horizons": tournament.horizons,
            "best_iteration": metrics["model"]["best_iteration"],
            "calibration": calibration,
            "calibration_target": "hospitalized_by_horizon",
            "calibration_fold": [str(final_fold.calibration[0]), str(final_fold.calibration[1])],
            "derived_from": {
                "metrics.json": ["model.best_iteration", "frozen_parameters", "calibration.<horizon>.parameters"],
                "ml/configs/tournament.yaml": ["horizons", "time_bins"],
            },
        }
        encoder = CategoricalFrameEncoder(categories)
        if spec["candidate"] == "xgboost_aft":
            booster = xgb.Booster(model_file=str(source / "model.json"))
            frozen = metrics["frozen_parameters"]
            inference["aft"] = {
                "distribution": frozen["aft_loss_distribution"],
                "scale": frozen["aft_loss_distribution_scale"],
            }
            model = AFTModel(
                booster,
                encoder,
                frozen["aft_loss_distribution"],
                float(frozen["aft_loss_distribution_scale"]),
                int(metrics["model"]["best_iteration"]),
            )
            matrix = xgb.DMatrix(encoder.transform(sample), enable_categorical=True)
            time_days = np.clip(booster.predict(matrix, iteration_range=(0, model.best_iteration + 1)), 1e-6, None)
            expected = {"referral_id": sample["referral_id"], "pred_time_days": time_days}
            algorithm = "XGBoost survival:aft (normal), hospitalization-only estimand"
        else:
            booster = lgb.Booster(model_file=str(source / "model.txt"))
            inference["hazard"] = {
                "time_bins": tournament.time_bins,
                "num_iteration": metrics["model"]["best_iteration"],
                "competing": False,
                "interval_feature": "time_interval",
            }
            model = HazardModel(booster, encoder, tournament.time_bins, False, int(metrics["model"]["best_iteration"]))
            expected = {"referral_id": sample["referral_id"]}
            algorithm = "LightGBM discrete-time hospitalization hazard over fixed day intervals"
        store._dump(target / "inference.json", inference)
        probabilities = model.probabilities(sample, tournament.horizons)
        for horizon in tournament.horizons:
            raw = probabilities[horizon]["hospitalized"]
            expected[f"p_hospitalized_{horizon}d_raw"] = raw
            calibrator = ProbabilityCalibrator.from_dict(calibration[str(horizon)])
            expected[f"p_hospitalized_{horizon}d"] = calibrator.predict(raw)
        write_csv(sample[["referral_id", "registration_date", *JOURNEY_FEATURES]], target / "example.csv.gz")
        write_csv(pd.DataFrame(expected), target / "example_expected.csv.gz")
        write_bundle(
            target / "bundle.joblib",
            {
                "name": name,
                "version": f"{TOURNAMENT_RUN}/{spec['directory']}",
                "model": booster,
                "features": JOURNEY_FEATURES,
                "categories": categories,
                "meta": meta,
                "inference": inference,
                "sha256_of_native_file": store.sha256_file(target / spec["native"]),
            },
        )
        principal = result["principal"]
        manifest_models[name] = {
            "algorithm": algorithm,
            "native_files": [spec["native"]],
            "source": {
                "artifact_path": source.relative_to(ROOT).as_posix(),
                "artifact_sha256": artifact_manifest["content_sha256"],
                "run_id": TOURNAMENT_RUN,
                "source_tournament": evidence["source_tournament"]["source_run_id"],
                "candidate": spec["candidate"],
                "trial_id": metrics["source_trial"],
                "fold": meta["fold"],
                "fold_windows": final_fold.model_dump(mode="json"),
                "label_cutoff": tournament.label_contract.cutoff.isoformat(),
                "full_cohort_rows": evidence["full_cohort_rows"],
                "parameter_source_checkpoint_ids": metrics["parameter_source_checkpoint_ids"],
                "concordance": principal["concordance"],
                "mean_hospitalization_brier_7_14_30": principal["mean_matching_horizon_brier"],
                "mean_calibration_error": principal["mean_target_calibration_error"],
                "decision": evidence["decision"]["recommendation"],
                "selection_note": (
                    "q1_final fold of the accepted full-cohort confirmation; its test metrics are the ones the "
                    "evidence index cites. The q1_fold_1 sibling is a shorter-history fold kept as evidence only."
                ),
            },
            "example": {
                "rows": len(sample),
                "population": f"eligible referrals registered in the {final_fold.id} test fold",
            },
        }
        log(f"{name}: {len(copied)} artifact files, example {len(sample)} rows")
    con.close()

    # ---- flow quantile refit (exported by export_flow_quantile_models.py when it reproduces the published values)
    flow_dir = out_root / "flow_quantile"
    if flow_dir.exists() and (flow_dir / "meta.json").exists():
        flow_meta = store.load_json(flow_dir, "meta.json")
        verification = (
            store.load_json(flow_dir, "verification.json") if (flow_dir / "verification.json").exists() else {}
        )
        manifest_models["flow_quantile"] = {
            "algorithm": flow_meta["algorithm"],
            "native_files": flow_meta["model_files"],
            "source": {
                "kind": (
                    "deterministic refit of the accepted run's final_test-origin boosters, "
                    "verified against its published raw quantiles"
                ),
                **flow_meta["refit_of"],
                "forecast_origin": flow_meta["forecast_origin"],
                "verification": {
                    target: {k: v for k, v in check.items() if k != "sample_series"}
                    for target, check in verification.items()
                },
            },
            "example": {"rows": None, "population": "sample of origin rows of directly supported series"},
        }

    # ---- manifest: every shipped file with its sha256
    built_with = {
        "python": sys.version.split()[0],
        "lightgbm": lgb.__version__,
        "xgboost": xgb.__version__,
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "joblib": __import__("joblib").__version__,
    }
    files = {}
    for path in sorted(out_root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.name in {"manifest.json", ".DS_Store"}:
            continue
        relative = path.relative_to(out_root).as_posix()
        model_name = relative.split("/", 1)[0] if "/" in relative else None
        if model_name in manifest_models:
            spec = manifest_models[model_name]
            if path.name in HAND_WRITTEN:
                origin = "hand-written"
            elif (
                path.name in spec["native_files"]
                or path.name
                in {
                    "artifact-manifest.json",
                    "meta.json",
                    "metrics.json",
                    "categories.json",
                    "display.json",
                    "series.json",
                }
                or (path.name == "features.json" and not model_name.startswith("patient_journey"))
            ):
                origin = "artifact (byte-identical)" if model_name != "flow_quantile" else "refit"
            else:
                origin = "generated"
        else:
            origin = "hand-written"
        files[relative] = {"bytes": path.stat().st_size, "sha256": store.sha256_file(path), "origin": origin}
    manifest = {
        "schema_version": 1,
        "rule": (
            "Frozen artefacts identified by sha256: a file whose digest differs from this manifest is a different "
            "model. Rebuild with `make models-export`; never edit shipped files by hand."
        ),
        "built_with": built_with,
        "models": manifest_models,
        "files": files,
        "total_bytes": sum(entry["bytes"] for entry in files.values()),
    }
    store._dump(out_root / "manifest.json", manifest, atomic=True)
    for relative, entry in files.items():
        log(f"  {relative:60s} {entry['bytes'] / 1e6:7.2f} MB")
    log(f"models/: {manifest['total_bytes'] / 1e6:.1f} MB in {len(files)} files -> {out_root / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
