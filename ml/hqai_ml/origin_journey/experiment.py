from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Any

import lightgbm
import numpy as np
import pandas as pd
import pyarrow
import scipy
import xgboost

from hqai_ml.origin_journey.aft import fit_aft
from hqai_ml.origin_journey.baseline import HierarchicalAJ
from hqai_ml.origin_journey.cohorts import SOURCE_COLUMNS, build_origin_cohorts
from hqai_ml.origin_journey.config import load_origin_journey_config
from hqai_ml.origin_journey.hashing import canonical_frame_sha256
from hqai_ml.origin_journey.hazard import fit_competing_hazard


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode()


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_bytes(value) + b"\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _stage(resources: dict, name: str, started: float) -> float:
    now = time.perf_counter()
    resources["stages"][name] = {
        "seconds": now - started,
        "process_peak_rss_bytes": _peak_rss_bytes(),
    }
    return now


def _library_versions() -> dict[str, str]:
    try:
        package_version = importlib.metadata.version("hqai-ml")
    except importlib.metadata.PackageNotFoundError:
        package_version = "0.1.0+source-tree"
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pyarrow": pyarrow.__version__,
        "scipy": scipy.__version__,
        "xgboost": xgboost.__version__,
        "lightgbm": lightgbm.__version__,
        "hqai_ml": package_version,
    }


def _flatten_predictions(
    scoring: pd.DataFrame,
    prediction_sets: dict[str, dict[int, dict[str, np.ndarray]]],
    aj_levels: list[str],
    intervals: pd.DataFrame,
    selected_model: str,
    coverage: float,
) -> pd.DataFrame:
    result = scoring[
        [
            "referral_id",
            "hospitalization_code",
            "org_code",
            "hospital_region_code",
            "profile_code",
            "registration_date",
            "days_waited_at_origin",
            "similar_training_rows",
            "has_similar_training_history",
        ]
    ].copy()
    result["aalen_johansen_level"] = aj_levels
    for model_name, probabilities in prediction_sets.items():
        for horizon, values in probabilities.items():
            for cause in ("hospitalized", "refused", "unresolved"):
                result[f"{model_name}__{cause}__{horizon}d"] = values[cause]
    result["selected_model"] = selected_model
    result["admission_interval_coverage"] = coverage
    for column in intervals:
        result[column] = intervals[column].to_numpy()
    return result.sort_values("referral_id", kind="stable").reset_index(drop=True)


def _interval_summary(intervals: pd.DataFrame, coverage: float, selected_model: str) -> dict:
    widths = intervals["admission_interval_width_days"].dropna()
    return {
        "selected_model": selected_model,
        "definition": (
            f"central {coverage:.0%} interval of admission time after the origin, conditional on a future "
            "admission within the model grid"
        ),
        "rows": int(len(intervals)),
        "rows_with_interval": int(len(widths)),
        "coverage_share": float(len(widths) / len(intervals)) if len(intervals) else 0.0,
        "width_days": {
            "median": float(widths.median()) if len(widths) else None,
            "p75": float(widths.quantile(0.75)) if len(widths) else None,
            "p90": float(widths.quantile(0.90)) if len(widths) else None,
            "mean": float(widths.mean()) if len(widths) else None,
        },
    }


def run_experiment(
    processed_referrals: Path,
    config_path: Path,
    output_dir: Path,
) -> dict:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing experiment directory: {output_dir}")
    output_dir.mkdir(parents=True)
    started = time.perf_counter()
    resources: dict[str, Any] = {
        "process_peak_rss_bytes_before": _peak_rss_bytes(),
        "stages": {},
    }
    library_versions = _library_versions()
    config = load_origin_journey_config(config_path)
    source = pd.read_parquet(processed_referrals, columns=list(SOURCE_COLUMNS))
    cohorts = build_origin_cohorts(source, config)
    checkpoint = _stage(resources, "cohort", started)

    baseline = HierarchicalAJ.fit(cohorts.training, config)
    baseline_probabilities, aj_levels = baseline.probabilities(cohorts.scoring, config.horizons)
    checkpoint = _stage(resources, "aalen_johansen", checkpoint)

    aft, aft_metadata = fit_aft(cohorts.training, config)
    aft_probabilities = aft.probabilities(cohorts.scoring, config.horizons)
    checkpoint = _stage(resources, "xgboost_aft", checkpoint)

    hazard, hazard_metadata = fit_competing_hazard(cohorts.training, config)
    hazard_probabilities = hazard.probabilities(cohorts.scoring, config.horizons)
    checkpoint = _stage(resources, "discrete_competing_risk", checkpoint)
    gc.collect()

    prediction_sets = {
        "aalen_johansen": baseline_probabilities,
        "xgboost_aft": aft_probabilities,
        "discrete_competing_risk": hazard_probabilities,
    }
    # Hindsight enters only after all models have been fitted and all predictions fixed.
    from hqai_ml.origin_journey.evaluation import (
        apply_decision_rule,
        build_evaluation_labels,
        evaluate_predictions,
    )

    labels = build_evaluation_labels(source, cohorts.scoring["referral_id"], config)
    metrics = evaluate_predictions(labels, cohorts.scoring, prediction_sets, config)
    decision = apply_decision_rule(metrics, config)
    selected_model = decision["selected_model"]
    coverage = config.evaluation.admission_interval_coverage
    if selected_model == "discrete_competing_risk":
        intervals = hazard.admission_intervals(cohorts.scoring, coverage)
    elif selected_model == "xgboost_aft":
        intervals = aft.admission_intervals(cohorts.scoring, coverage)
    else:
        intervals = baseline.admission_intervals(cohorts.scoring, coverage, config.time_grid.coarse_edges[-1])
    interval_summary = _interval_summary(intervals, coverage, selected_model)
    predictions = _flatten_predictions(
        cohorts.scoring,
        prediction_sets,
        aj_levels,
        intervals,
        selected_model,
        coverage,
    )
    checkpoint = _stage(resources, "evaluation", checkpoint)

    _write_json(output_dir / "config.json", config.model_dump(mode="json"))
    _write_json(output_dir / "cohort-audit.json", cohorts.audit)
    _write_json(output_dir / "aalen-johansen.json", baseline.to_dict())
    aft.booster.save_model(output_dir / "xgboost-aft.json")
    (output_dir / "lightgbm-competing-hazard.txt").write_text(
        hazard.booster.model_to_string(num_iteration=hazard.iterations),
        encoding="utf-8",
    )
    _write_json(
        output_dir / "model-metadata.json",
        {
            "xgboost_aft": {**aft_metadata, "encoder": aft.encoder.to_dict()},
            "discrete_competing_risk": {**hazard_metadata, "encoder": hazard.encoder.to_dict()},
        },
    )
    _write_json(output_dir / "metrics.json", metrics)
    _write_json(output_dir / "decision.json", decision)
    _write_json(output_dir / "admission-interval-summary.json", interval_summary)
    predictions.to_csv(
        output_dir / "predictions.csv",
        index=False,
        lineterminator="\n",
        na_rep="",
        float_format="%.12g",
    )
    resources["total_seconds"] = time.perf_counter() - started
    resources["process_peak_rss_bytes_at_completion"] = _peak_rss_bytes()
    run = {
        "schema_version": 1,
        "seed": config.seed,
        "origin": config.origin.isoformat(),
        "training_sha256": canonical_frame_sha256(cohorts.training),
        "scoring_sha256": canonical_frame_sha256(cohorts.scoring),
        "library_versions": library_versions,
        "resources": resources,
        "determinism": {
            "fixed_seed": True,
            "stable_referral_order": True,
            "lightgbm_deterministic": True,
            "canonical_json": True,
        },
    }
    _write_json(output_dir / "run.json", run)

    files = []
    for path in sorted(output_dir.iterdir()):
        if path.name == "manifest.json":
            continue
        files.append({"path": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size})
    identity = hashlib.sha256(_canonical_bytes(files)).hexdigest()
    scientific_files = [row for row in files if row["path"] != "run.json"]
    scientific_identity = hashlib.sha256(_canonical_bytes(scientific_files)).hexdigest()
    manifest = {
        "schema_version": 1,
        "artifact_identity_sha256": identity,
        "scientific_identity_sha256": scientific_identity,
        "scientific_identity_excludes": ["run.json (execution time and peak RSS vary by run)"],
        "files": files,
    }
    _write_json(output_dir / "manifest.json", manifest)
    return {
        "output_dir": str(output_dir),
        "artifact_identity_sha256": identity,
        "scientific_identity_sha256": scientific_identity,
        "decision": decision,
        "interval_summary": interval_summary,
        "resources": resources,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate origin-journey B2 candidates")
    parser.add_argument("--referrals", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(
        json.dumps(
            run_experiment(arguments.referrals, arguments.config, arguments.output),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
