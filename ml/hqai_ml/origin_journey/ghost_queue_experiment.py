from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from hqai_ml.origin_journey.baseline import HierarchicalAJ
from hqai_ml.origin_journey.cohorts import SOURCE_COLUMNS, build_origin_cohorts
from hqai_ml.origin_journey.config import load_origin_journey_config
from hqai_ml.origin_journey.ghost_queue import build_ghost_queue_bundle, write_ghost_queue_bundle


def _pct(value: float | None) -> str:
    return "not estimable" if value is None else f"{value:.1%}"


def _calibration_table(calibration: dict) -> str:
    lines = [
        "| Slice | Flagged | Mean modeled P(admit 90d) | Actually admitted within 90d | Observed share |",
        "|---|---:|---:|---:|---:|",
    ]
    rows = [("overall", calibration["overall"])]
    rows.extend((f"wait {key}", value) for key, value in calibration["by_days_waited_bucket"].items())
    rows.extend((f"tier {key}", value) for key, value in calibration["by_support_tier"].items())
    for label, row in rows:
        lines.append(
            f"| {label} | {row['flagged']} | {_pct(row['mean_model_probability_admitted_90d'])} | "
            f"{row['admitted_within_90d']} | {_pct(row['observed_admitted_within_90d_share'])} |"
        )
    return "\n".join(lines)


def _yield_table(evaluation: dict) -> str:
    lines = [
        "| Top N | Evaluated | True ghosts | Yield | Lift vs base |",
        "|---:|---:|---:|---:|---:|",
    ]
    for cutoff, row in evaluation["yield_curve"].items():
        lines.append(
            f"| {cutoff} | {row['evaluation_eligible']} | {row['true_ghosts']} | {_pct(row['yield'])} | "
            f"{row['lift_vs_base']:.2f}× |"
        )
    return "\n".join(lines)


def _regional_yield_table(evaluation: dict) -> str:
    cutoffs = list(evaluation["yield_curve"])
    lines = [
        "| Region | Regional base | " + " | ".join(f"Top {cutoff}: n / yield" for cutoff in cutoffs) + " |",
        "|---|---:|" + "---:|" * len(cutoffs),
    ]
    for region, result in sorted(evaluation["yield_curve_by_region"].items()):
        cells = []
        for cutoff in cutoffs:
            point = result["points"].get(cutoff)
            cells.append("—" if point is None else f"{point['evaluation_eligible']} / {_pct(point['yield'])}")
        lines.append(f"| {region} | {_pct(result['base_rate'])} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _fact_table(rows: list[dict], key: str, label: str) -> str:
    lines = [
        f"| {label} | Origin waiters | Later refused | Still open at cutoff |",
        "|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row[key]} | {row['origin_waiters']} | {row['later_refused']} | {row['still_open_at_cutoff']} |"
        )
    return "\n".join(lines)


def _summary(bundle: dict, evaluation: dict, name: str, size: int, file_sha256: str) -> str:
    headline = bundle["headline"]
    facts = evaluation["hindsight_fact_block"]
    months = bundle["ranking"]["recommended_history_months"]
    return f"""# Ghost-queue verification worklist — origin {bundle["origin"]}

The bundle was frozen before hindsight evaluation. It ranks verification work; it does not declare referrals stale.

## Headline

- Formal queue: {headline["formal_queue_count"]}
- Ranked worklist: {headline["ranked_verification_worklist_count"]}
- Degenerate or unsupported history warning: {headline["history_quality_warning_count"]}
  ({headline["history_quality_warning_share"]:.1%})

Training-only score: `(1 - P(admission within 90d)) × min(days waited / 30, 1) ×
min(comparable at-risk training rows / 50, 1)`. Higher scores are reviewed first. Ties use longer wait, then referral
ID. {bundle["ranking"]["training_only_justification"]}

## Calibration of the old binary claim

The old rule claimed less than 10% admission probability for referrals already waiting at least 30 days. The table
below compares that claim with admission within 90 days after the origin. It is hindsight evaluation only.

{_calibration_table(evaluation["flag_claim_calibration"])}

## Verification yield

The formal-queue ghost base rate is {evaluation["base_rate"]:.1%}. A ghost is a referral with no admission before
the cutoff: later refused or still open. The ordering and cutoffs were fixed before this evaluation.

{_yield_table(evaluation)}

### Yield by region within each global top-N slice

{_regional_yield_table(evaluation)}

## Hindsight facts — evaluation only, not model output

Across {facts["overall"]["origin_waiters"]} origin waiters, {facts["overall"]["later_refused"]} were later refused
and {facts["overall"]["still_open_at_cutoff"]} remained open at the exclusive 2026-05-13 cutoff. These counts are
not present in the JSON bundle.

### By region

{_fact_table(facts["by_region"], "hospital_region_code", "Region")}

### By profile

{_fact_table(facts["by_profile"], "profile_code", "Profile")}

## Limitations in plain words

- Source history starts on 2025-01-01, so referrals already waiting 60+ days have little comparable history.
- A zero or near-zero probability can mean the assigned risk set ran out, not that admission is impossible.
- Warning reason codes should be shown as `мало сопоставимой истории`, not as a confident probability.
- About {months} months of data would provide real long-wait history.
- Scores prioritize clerical verification and must not drive clinical or administrative removal.

## Artifact

- File: `{name}`
- Bytes: {size}
- Publication identity SHA-256: `{bundle["publication_identity_sha256"]}`
- Compressed-file SHA-256: `{file_sha256}`
- Hindsight fields in bundle: none
"""


def run_ghost_queue_experiment(referrals_path: Path, config_path: Path, output_dir: Path) -> dict:
    config = load_origin_journey_config(config_path)
    source = pd.read_parquet(referrals_path, columns=list(SOURCE_COLUMNS))
    cohorts = build_origin_cohorts(source, config)
    model = HierarchicalAJ.fit(cohorts.training, config)
    bundle = build_ghost_queue_bundle(cohorts.scoring, model, config)

    stem = f"ghost-queue-{config.origin.isoformat()}-v{config.ghost_queue.schema_version}"
    bundle_path = output_dir / f"{stem}.json.gz"
    summary_path = output_dir / f"{stem}.md"
    for path in (bundle_path, summary_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing B5.1 output: {path}")
    bundle_bytes, bundle_sha256 = write_ghost_queue_bundle(bundle_path, bundle)

    # Hindsight is imported only after the public bundle is fixed on disk.
    from hqai_ml.origin_journey.evaluation import evaluate_ghost_queue_bundle

    evaluation = evaluate_ghost_queue_bundle(bundle, source, config)
    summary = _summary(bundle, evaluation, bundle_path.name, bundle_bytes, bundle_sha256)
    summary_path.write_text(summary, encoding="utf-8", newline="\n")
    return {
        "bundle": str(bundle_path),
        "summary": str(summary_path),
        "bundle_bytes": bundle_bytes,
        "bundle_sha256": bundle_sha256,
        "publication_identity_sha256": bundle["publication_identity_sha256"],
        "summary_sha256": hashlib.sha256(summary.encode()).hexdigest(),
        "headline": bundle["headline"],
        "evaluation": evaluation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and evaluate the origin-safe ghost-queue worklist")
    parser.add_argument("--referrals", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    result = run_ghost_queue_experiment(arguments.referrals, arguments.config, arguments.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
