#!/usr/bin/env python3
"""Refit and export the final-origin p10/p50/p90 flow quantile boosters as standalone model files.

The accepted flow-quantile evidence run (artifacts/flow_quantile/flow-quantile-6b2b2-real-v1) persisted
predictions, not boosters: hqai_ml.flow_forecast.quantile fits three LightGBM quantile objectives per origin and
target and keeps only the evaluation frame. This script rebuilds the final_test-origin training frame with the same
code and configuration, fits the boosters again with the accepted run's thread count, and verifies the refit against
the published raw quantiles of directly supported series before anything is written under models/flow_quantile/.
A refit that does not reproduce the published values within tolerance ships nothing.

Run:  PYTHONPATH=ml .venv/bin/python ml/pipelines/export_flow_quantile_models.py [--targets registrations]
Reads data/processed/*.parquet and the accepted evaluation parquet only (no Postgres, no science changes).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from hqai_ml.registry.resources import apply_resource_environment, resource_config

STARTED = time.perf_counter()
ROOT = Path(__file__).resolve().parents[2]
ACCEPTED_RUN = "flow-quantile-6b2b2-real-v1"
ACCEPTED_ORIGIN_DIR = "final_test-2025-03-17-f511b8990d57"
RELATIVE_TOLERANCE = 1e-3
VERIFICATION_SAMPLE = 200
EXAMPLE_ROWS = 42


def log(message: str) -> None:
    print(f"[{time.perf_counter() - STARTED:7.1f}s] {message}", flush=True)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "models" / "flow_quantile")
    parser.add_argument("--targets", nargs="+", default=["registrations", "cohort_hospitalizations"])
    parser.add_argument(
        "--ship-targets",
        nargs="+",
        default=["registrations"],
        help="verified targets whose boosters are written; the rest are verified only, to keep models/ small",
    )
    parser.add_argument("--model-threads", type=int, default=4, help="the accepted run trained with 4 threads")
    parser.add_argument("--tolerance", type=float, default=RELATIVE_TOLERANCE)
    parser.add_argument("--scratch", type=Path, help="write boosters here first; only --out on success")
    return parser.parse_args()


def published_direct_rows(target: str):
    import pandas as pd

    path = ROOT / "artifacts" / "flow_quantile" / ACCEPTED_RUN / "origins" / ACCEPTED_ORIGIN_DIR / "evaluation.parquet"
    frame = pd.read_parquet(
        path,
        filters=[
            ("phase", "==", "final_test"),
            ("candidate", "==", "quantile_lightgbm"),
            ("variant", "==", "raw"),
            ("target", "==", target),
            ("prediction_source", "==", "direct_quantile_ml"),
        ],
    )
    return frame, path


def compare(refit, published, tolerance: float) -> dict:
    """Max absolute and relative difference over every directly supported cell and over a 200-series sample."""
    import numpy as np

    merged = published.merge(refit, on=["series_id", "horizon"], how="left", validate="one_to_one")
    if merged[["refit_p10", "refit_p50", "refit_p90"]].isna().any().any():
        raise ValueError("refit is missing directly supported cells that the accepted run published")
    hospital_series = sorted(merged.loc[merged["level"] == "hospital", "series_id"].unique())
    rng = np.random.default_rng(42)
    sample = sorted(rng.choice(hospital_series, size=min(VERIFICATION_SAMPLE, len(hospital_series)), replace=False))
    result = {
        "tolerance_relative": tolerance,
        "cells_compared": int(len(merged)),
        "series_compared": len(hospital_series),
    }
    for scope, part in (
        ("all_direct_cells", merged),
        ("hospital_sample_200_series", merged[merged["series_id"].isin(sample)]),
    ):
        abs_diff = np.zeros(len(part))
        rel_diff = np.zeros(len(part))
        for column in ("p10", "p50", "p90"):
            published_values = part[column].to_numpy(float)
            diff = np.abs(part[f"refit_{column}"].to_numpy(float) - published_values)
            abs_diff = np.maximum(abs_diff, diff)
            rel_diff = np.maximum(rel_diff, diff / np.maximum(np.abs(published_values), 1.0))
        result[scope] = {
            "cells": int(len(part)),
            "series": int(part["series_id"].nunique()),
            "max_abs_difference": float(abs_diff.max()),
            "max_relative_difference": float(rel_diff.max()),
            "relative_denominator": "max(|published|, 1)",
            "within_tolerance": bool(rel_diff.max() <= tolerance),
        }
    result["sample_series"] = sample
    result["within_tolerance"] = all(
        result[k]["within_tolerance"] for k in ("all_direct_cells", "hospital_sample_200_series")
    )
    return result


def main() -> int:
    args = parse_args()
    resources = resource_config("laptop", model_threads=args.model_threads, parallel_trials=1, process_concurrency=1)
    apply_resource_environment(resources)

    import pandas as pd

    from hqai_ml.features.data import connect
    from hqai_ml.features.load import SERIES_CATEGORICAL, build_rows, feature_names, load_panels
    from hqai_ml.flow_forecast.config import load_flow_quantile_config
    from hqai_ml.flow_forecast.evidence import combine_panels, national_panel, support_mask
    from hqai_ml.flow_forecast.quantile import INTERNAL_TARGETS, QUANTILE_COLUMNS, QUANTILES, fit_quantile_target
    from hqai_ml.ingest.config import IngestSettings
    from hqai_ml.models.config import load_model_config
    from hqai_ml.models.lgbm import encode, fit_categories
    from hqai_ml.registry import store
    from hqai_ml.registry.resources import seed_process

    settings = IngestSettings()
    config = load_flow_quantile_config(settings.configs_dir / "flow_quantile.yaml")
    model_config = load_model_config(settings)
    model_config.lightgbm = {**model_config.lightgbm, "num_threads": resources.model_threads}
    seed_process(config.seed)
    run = json.loads((settings.artifacts_dir / "runs" / ACCEPTED_RUN / "run.json").read_text(encoding="utf-8"))
    accepted_threads = run["executions"][-1]["resources"]["model_threads"]
    if accepted_threads != resources.model_threads:
        log(f"warning: accepted run used {accepted_threads} model threads, refitting with {resources.model_threads}")

    con = connect(settings.processed_dir, resources)
    hospital, region = load_panels(con)
    con.close()
    panels = {"hospital": hospital, "region": region, "national": national_panel(region)}
    all_panel = combine_panels(panels.values())
    origin = config.final_test_origin
    origin_index = all_panel.index_of(origin)
    lf = model_config.load_forecast
    features = feature_names(lf.lags, lf.rolling)
    staging = args.scratch or (args.out.parent / f".{args.out.name}.partial")
    staging.mkdir(parents=True, exist_ok=True)

    verification = {}
    exported = {}
    example_parts = []
    for public_target in args.targets:
        target = INTERNAL_TARGETS[public_target]
        masks = {level: support_mask(panel, target, origin_index, config) for level, panel in panels.items()}
        supported_panels = [
            panel.subset(masks[level]) for level, panel in panels.items() if level != "national" and masks[level].any()
        ]
        direct_panel = combine_panels(supported_panels)
        categories = fit_categories(direct_panel.meta, SERIES_CATEGORICAL)
        rows = build_rows(
            direct_panel, target, [origin_index], config.horizon, lf.lags, lf.rolling, set(lf.holidays), None
        )
        encoded = encode(rows, features, categories)
        refit = rows[["series_id", "horizon"]].copy()
        boosters = {}
        for quantile in QUANTILES:
            log(f"fit {public_target} {QUANTILE_COLUMNS[quantile]} on {len(direct_panel.meta)} direct series")
            booster = fit_quantile_target(
                direct_panel, target, origin_index, quantile, categories, config, model_config
            )
            boosters[quantile] = booster
            refit[f"refit_{QUANTILE_COLUMNS[quantile]}"] = booster.predict(encoded)
        published, published_path = published_direct_rows(public_target)
        check = compare(refit, published, args.tolerance)
        check["published_source"] = published_path.relative_to(ROOT).as_posix()
        verification[public_target] = check
        overall = check["all_direct_cells"]
        log(
            f"verify {public_target}: {check['cells_compared']} cells, max abs {overall['max_abs_difference']:.3e}, "
            f"max rel {overall['max_relative_difference']:.3e}, within tolerance={check['within_tolerance']}"
        )
        if not check["within_tolerance"] or public_target not in args.ship_targets:
            continue
        for quantile, booster in boosters.items():
            filename = f"model_{public_target}_{QUANTILE_COLUMNS[quantile]}.txt"
            booster.save_model(str(staging / filename))
            exported[filename] = {"target": public_target, "quantile": quantile, "trees": booster.num_trees()}
        store._dump(staging / f"categories_{public_target}.json", categories)
        sample = rows.sample(n=EXAMPLE_ROWS, random_state=42).sort_values(["series_id", "horizon"])
        numeric = [feature for feature in features if feature not in SERIES_CATEGORICAL]
        example = sample[["series_id", *features]].astype(dict.fromkeys(numeric, "float64"))
        example.insert(0, "target", public_target)
        expected = sample[["series_id", "horizon"]].copy()
        expected.insert(0, "target", public_target)
        for quantile in QUANTILES:
            expected[QUANTILE_COLUMNS[quantile]] = boosters[quantile].predict(encode(sample, features, categories))
        example_parts.append((example, expected))

    if not exported:
        log("no target reproduced the published quantiles; nothing exported")
        (staging / "verification.json").write_text(store.canonical_json(verification), encoding="utf-8")
        return 1

    example = pd.concat([part for part, _ in example_parts], ignore_index=True)
    expected = pd.concat([part for _, part in example_parts], ignore_index=True)
    gzip_settings = {"method": "gzip", "mtime": 0, "compresslevel": 9}
    example.to_csv(staging / "example.csv.gz", index=False, float_format="%.17g", compression=gzip_settings)
    expected.to_csv(staging / "example_expected.csv.gz", index=False, float_format="%.17g", compression=gzip_settings)
    store._dump(staging / "features.json", {"features": features, "categorical": SERIES_CATEGORICAL})
    store._dump(
        staging / "meta.json",
        {
            "model_name": "flow_quantile",
            "version": f"{ACCEPTED_RUN}-refit-{origin}",
            "algorithm": "three independent LightGBM quantile objectives per target (alpha 0.1, 0.5, 0.9)",
            "targets": {
                name: {
                    "verified_against_published": verification[name]["within_tolerance"],
                    "exported": any(v["target"] == name for v in exported.values()),
                }
                for name in args.targets
            },
            "model_files": sorted(exported),
            "forecast_origin": str(origin),
            "horizons": list(range(1, config.horizon + 1)),
            "training_rows": (
                "every directly supported series, cutoffs from day index 6 up to the origin, "
                "targets on or before the origin"
            ),
            "training_data_through": str(origin),
            "lightgbm_params": {**model_config.lightgbm, "objective": "quantile", "metric": "quantile"},
            "num_boost_round": config.challenger.rounds,
            "quantiles": {QUANTILE_COLUMNS[q]: q for q in QUANTILES},
            "feature_contract": "hqai_ml.features.load.build_rows (feature_names in features.json)",
            "refit_of": {
                "run_id": ACCEPTED_RUN,
                "origin_artifact": f"artifacts/flow_quantile/{ACCEPTED_RUN}/origins/{ACCEPTED_ORIGIN_DIR}",
                "scientific_identity_sha256": run["scientific_identity_sha256"],
                "dataset_identity": run["dataset"]["identity_sha256"],
                "config_identity": run["configuration"]["sha256"],
                "code_identity": run["code"]["source"]["sha256"],
                "model_threads": resources.model_threads,
            },
        },
    )
    store._dump(staging / "verification.json", verification)
    args.out.mkdir(parents=True, exist_ok=True)
    for path in sorted(staging.iterdir()):
        target_path = args.out / path.name
        target_path.write_bytes(path.read_bytes())
        path.unlink()
    staging.rmdir()
    for filename, info in exported.items():
        log(f"  {filename}: {info['trees']} trees, {(args.out / filename).stat().st_size / 1e6:.1f} MB")
    log(f"exported to {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
