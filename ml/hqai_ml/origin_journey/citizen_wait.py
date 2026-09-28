"""Build the deterministic, aggregate-only citizen wait-estimate publication."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hqai_ml.origin_journey.baseline import AJCurve, HierarchicalAJ
from hqai_ml.origin_journey.config import OriginJourneyConfig

TIER_NAMES = {
    "org_codexprofile_code": "hospital_profile",
    "hospital_region_codexprofile_code": "region_profile",
    "profile_code": "profile",
    "global": "global",
}
FORBIDDEN_PUBLIC_KEYS = {
    "referral_id",
    "hospitalization_code",
    "hospitalization_date",
    "refusal_date",
    "resolution_date",
    "outcome",
    "evaluation",
    "actual_admission_days",
    "event_date",
}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


def _conditional_admission_quantile(curve: AJCurve, probability: float) -> float | None:
    """Quantile of admission time among the curve's eventual admissions."""
    if not len(curve.hospitalized_cif) or curve.hospitalized_cif[-1] <= 1e-12:
        return None
    threshold = probability * float(curve.hospitalized_cif[-1])
    position = int(np.searchsorted(curve.hospitalized_cif, threshold, side="left"))
    if position >= len(curve.event_times):
        return None
    return float(curve.event_times[position])


def _hospital_region(group: pd.DataFrame) -> str:
    values = group["hospital_region_code"].dropna().astype(str)
    if values.empty:
        return "<missing>"
    counts = values.value_counts()
    highest = int(counts.max())
    return sorted(counts[counts == highest].index)[0]


def _candidate_cells(training: pd.DataFrame) -> pd.DataFrame:
    eligible = training.loc[training["label_eligible"]]
    rows = []
    for (org_code, profile_code), group in eligible.groupby(["org_code", "profile_code"], sort=True, dropna=False):
        rows.append(
            {
                "org_code": "<missing>" if pd.isna(org_code) else str(org_code),
                "profile_code": "<missing>" if pd.isna(profile_code) else str(profile_code),
                "hospital_region_code": _hospital_region(group),
                "hospital_training_rows": int(len(group)),
            }
        )
    return pd.DataFrame(rows).sort_values(["org_code", "profile_code"], kind="stable").reset_index(drop=True)


def build_citizen_wait_bundle(
    training: pd.DataFrame,
    model: HierarchicalAJ,
    config: OriginJourneyConfig,
) -> dict[str, Any]:
    """Produce origin-safe aggregate cells; this path has no hindsight dependency."""
    cells = _candidate_cells(training)
    assignments = model.assignments(cells)
    output_cells = []
    tier_counts = dict.fromkeys(TIER_NAMES.values(), 0)
    suppressed = 0
    threshold = config.citizen_wait.minimum_hospital_training_rows
    for row, (raw_tier, _, curve) in zip(cells.itertuples(index=False), assignments, strict=True):
        tier = TIER_NAMES[raw_tier]
        hospital_suppressed = row.hospital_training_rows < threshold
        if hospital_suppressed:
            suppressed += 1
            if tier == "hospital_profile":
                raise ValueError("a privacy-suppressed cell cannot use a hospital-level curve")
        elif tier != "hospital_profile":
            raise ValueError("a supported hospital cell unexpectedly fell back")
        median = _conditional_admission_quantile(curve, config.citizen_wait.admission_quantiles[0])
        admitted_80 = _conditional_admission_quantile(curve, config.citizen_wait.admission_quantiles[1])
        refusal_30 = float(curve.state(float(config.citizen_wait.refusal_horizon_days))[1])
        output_cells.append(
            {
                "org_code": row.org_code,
                "hospital_region_code": row.hospital_region_code,
                "profile_code": row.profile_code,
                "estimate_tier": tier,
                "hospital_estimate_suppressed": hospital_suppressed,
                "median_days_to_admission": median,
                "admitted_80pct_by_day": admitted_80,
                "refusal_probability_30d": refusal_30,
                "admission_quantile_status": {
                    "median": "estimated" if median is not None else "not_reached_in_origin_safe_curve",
                    "p80": "estimated" if admitted_80 is not None else "not_reached_in_origin_safe_curve",
                },
            }
        )
        tier_counts[tier] += 1

    projection = {
        "schema_version": config.citizen_wait.schema_version,
        "publication_id": f"citizen-wait-{config.origin.isoformat()}-v{config.citizen_wait.schema_version}",
        "origin": config.origin.isoformat(),
        "model": "origin-safe hierarchical Aalen-Johansen",
        "estimands": {
            "admission_time_conditioning": config.citizen_wait.admission_quantile_estimand,
            "median_days_to_admission": (
                "50th percentile of admission time among admissions within the origin-safe observable curve"
            ),
            "admitted_80pct_by_day": (
                "80th percentile of admission time among admissions within the origin-safe observable curve"
            ),
            "refusal_probability_30d": "competing-risk cumulative refusal incidence by day 30",
        },
        "privacy": {
            "minimum_hospital_training_rows": threshold,
            "suppression_justification": config.citizen_wait.suppression_justification,
            "fallback_order": ["region_profile", "profile", "global"],
            "small_cell_counts_published": False,
        },
        "publication_counts": {
            "cells": len(output_cells),
            "hospital_level_suppressed_cells": suppressed,
            "by_estimate_tier": tier_counts,
        },
        "limitations": [
            "Estimates describe historical competing-risk incidence and are not a promise of an admission date.",
            "Source referrals start on 2025-01-01, so longer pre-existing waits are absent.",
            "A null admission quantile means the origin-safe curve did not reach that incidence, not infinite wait.",
        ],
        "cells": output_cells,
    }
    identity = hashlib.sha256(canonical_json_bytes(projection)).hexdigest()
    bundle = {**projection, "publication_identity_sha256": identity}
    validate_citizen_wait_bundle(bundle)
    return bundle


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def validate_citizen_wait_bundle(bundle: dict[str, Any]) -> None:
    if FORBIDDEN_PUBLIC_KEYS & _all_keys(bundle):
        raise ValueError("citizen bundle contains a per-referral or hindsight field")
    projection = dict(bundle)
    supplied_identity = projection.pop("publication_identity_sha256", None)
    expected_identity = hashlib.sha256(canonical_json_bytes(projection)).hexdigest()
    if supplied_identity != expected_identity:
        raise ValueError("citizen bundle identity does not match its canonical content")
    threshold = bundle["privacy"]["minimum_hospital_training_rows"]
    if threshold <= 0:
        raise ValueError("privacy threshold must be positive")
    identifiers = []
    for cell in bundle["cells"]:
        identifiers.append((cell["org_code"], cell["profile_code"]))
        probability = cell["refusal_probability_30d"]
        if not 0 <= probability <= 1:
            raise ValueError("refusal probability lies outside [0, 1]")
        median = cell["median_days_to_admission"]
        p80 = cell["admitted_80pct_by_day"]
        if median is not None and p80 is not None and median > p80:
            raise ValueError("admission quantiles are not monotone")
        if cell["hospital_estimate_suppressed"] and cell["estimate_tier"] == "hospital_profile":
            raise ValueError("suppressed cell exposes a hospital estimate")
    if identifiers != sorted(set(identifiers)):
        raise ValueError("citizen cells must be unique and deterministically sorted")


def write_citizen_wait_bundle(path: Path, bundle: dict[str, Any]) -> tuple[int, str]:
    """Write canonical JSON in a reproducible gzip stream (zero mtime, no filename)."""
    validate_citizen_wait_bundle(bundle)
    raw = canonical_json_bytes(bundle) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        path.open("wb") as stream,
        gzip.GzipFile(filename="", mode="wb", fileobj=stream, compresslevel=9, mtime=0) as gz,
    ):
        gz.write(raw)
    payload = path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()
