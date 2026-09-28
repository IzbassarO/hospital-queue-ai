from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from hqai_ml.origin_journey.baseline import HierarchicalAJ
from hqai_ml.origin_journey.citizen_wait import build_citizen_wait_bundle, write_citizen_wait_bundle
from hqai_ml.origin_journey.cohorts import SOURCE_COLUMNS, build_origin_cohorts
from hqai_ml.origin_journey.config import load_origin_journey_config


def _pct(value: float | None) -> str:
    return "not estimable" if value is None else f"{value:.1%}"


def _evaluation_table(evaluation: dict) -> str:
    rows = [("overall", evaluation["overall"]), *sorted(evaluation["by_support_tier"].items())]
    lines = [
        "| Tier | Registered | Valid admissions | Median evaluable | By median | P80 evaluable | By P80 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for tier, row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    tier,
                    str(row["registered_referrals"]),
                    str(row["valid_admissions"]),
                    str(row["median_evaluable_admissions"]),
                    _pct(row["admitted_by_median_share"]),
                    str(row["p80_evaluable_admissions"]),
                    _pct(row["admitted_by_p80_share"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _summary(
    bundle: dict,
    evaluation: dict,
    bundle_name: str,
    bundle_bytes: int,
    bundle_sha256: str,
) -> str:
    counts = bundle["publication_counts"]
    tiers = counts["by_estimate_tier"]
    threshold = bundle["privacy"]["minimum_hospital_training_rows"]
    suppressed = counts["hospital_level_suppressed_cells"]
    unpublished = evaluation["unpublished_referrals"]
    return f"""# Citizen wait estimates — origin {bundle["origin"]}

Selected estimator: hierarchical Aalen–Johansen competing-risk cumulative incidence. No per-referral or hindsight
fields are present in `{bundle_name}`.

## Publication

- Cells: {counts["cells"]}
- Hospital-specific: {tiers["hospital_profile"]}
- Region × profile fallback: {tiers["region_profile"]}
- Profile fallback: {tiers["profile"]}
- Global fallback: {tiers["global"]}
- Hospital cells suppressed by the <{threshold} rule: {suppressed}
- Bundle bytes: {bundle_bytes}
- Publication identity SHA-256: `{bundle["publication_identity_sha256"]}`
- Compressed-file SHA-256: `{bundle_sha256}`

Privacy rule: {bundle["privacy"]["suppression_justification"]}

## Locked hindsight evaluation: 18–31 March registrations

Rates use valid eventual admissions with a published, non-null quantile. This evaluation was not used to tune the
threshold, hierarchy, quantiles, or model.

{_evaluation_table(evaluation)}

Unpublished new-referral rows because their hospital × profile cell did not exist at the origin: {unpublished}.

## Interpretation

`median_days_to_admission` and `admitted_80pct_by_day` describe admission time conditional on eventual admission
within the origin-safe observable curve. In citizen-facing language: among similar referrals that are admitted, half
are admitted by the median and 80% by the latter day. Refusal remains a separate competing-risk probability. These
are population estimates, not promised dates for an individual.
"""


def run_citizen_wait_experiment(
    referrals_path: Path,
    config_path: Path,
    output_dir: Path,
) -> dict:
    config = load_origin_journey_config(config_path)
    source = pd.read_parquet(referrals_path, columns=list(SOURCE_COLUMNS))
    cohorts = build_origin_cohorts(source, config)
    baseline = HierarchicalAJ.fit(cohorts.training, config)
    bundle = build_citizen_wait_bundle(cohorts.training, baseline, config)

    stem = f"citizen-wait-{config.origin.isoformat()}-v{config.citizen_wait.schema_version}"
    bundle_path = output_dir / f"{stem}.json.gz"
    summary_path = output_dir / f"{stem}.md"
    for path in (bundle_path, summary_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing B4 output: {path}")
    bundle_bytes, bundle_sha256 = write_citizen_wait_bundle(bundle_path, bundle)

    # The public artifact is fixed before eventual outcomes are loaded by the isolated evaluation path.
    from hqai_ml.origin_journey.evaluation import evaluate_citizen_wait_bundle

    evaluation = evaluate_citizen_wait_bundle(bundle, source, config)
    summary = _summary(bundle, evaluation, bundle_path.name, bundle_bytes, bundle_sha256)
    summary_path.write_text(summary, encoding="utf-8", newline="\n")
    return {
        "bundle": str(bundle_path),
        "summary": str(summary_path),
        "bundle_bytes": bundle_bytes,
        "bundle_sha256": bundle_sha256,
        "publication_identity_sha256": bundle["publication_identity_sha256"],
        "summary_sha256": hashlib.sha256(summary.encode()).hexdigest(),
        "publication_counts": bundle["publication_counts"],
        "evaluation": evaluation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and evaluate aggregate citizen-facing wait estimates")
    parser.add_argument("--referrals", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    result = run_citizen_wait_experiment(arguments.referrals, arguments.config, arguments.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
