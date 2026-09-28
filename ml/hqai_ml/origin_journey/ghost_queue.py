"""Origin-safe ghost-queue estimates and deterministic publication."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hqai_ml.origin_journey.baseline import HierarchicalAJ
from hqai_ml.origin_journey.citizen_wait import TIER_NAMES, canonical_json_bytes
from hqai_ml.origin_journey.config import OriginJourneyConfig

FORBIDDEN_GHOST_KEYS = {
    "hospitalization_date",
    "refusal_date",
    "evaluation_event_type",
    "evaluation_event_date",
    "hindsight",
    "is_actual_ghost",
    "actual_outcome",
}


def _text(value: Any) -> str:
    return "<missing>" if pd.isna(value) else str(value)


def _conditional_state(curve, start_day: float, end_day: float) -> tuple[float, float, float]:
    start_admission, start_refusal, start_survival = curve.state(start_day)
    end_admission, end_refusal, end_survival = curve.state(end_day)
    if float(start_survival) <= 1e-12:
        return 0.0, 0.0, 1.0
    denominator = float(start_survival)
    admitted = float(np.clip((float(end_admission) - float(start_admission)) / denominator, 0.0, 1.0))
    refused = float(np.clip((float(end_refusal) - float(start_refusal)) / denominator, 0.0, 1.0))
    unresolved = float(np.clip(float(end_survival) / denominator, 0.0, 1.0))
    total = admitted + refused + unresolved
    if total <= 1e-12:
        return 0.0, 0.0, 1.0
    return admitted / total, refused / total, unresolved / total


def _aggregate(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    rows = []
    grouper: str | list[str] = columns[0] if len(columns) == 1 else columns
    for raw_key, group in frame.groupby(grouper, sort=True, dropna=False):
        keys = raw_key if isinstance(raw_key, tuple) else (raw_key,)
        formal = int(len(group))
        warning = int(group["history_quality_warning"].sum())
        row = {column: _text(value) for column, value in zip(columns, keys, strict=True)}
        row.update(
            {
                "formal_queue_count": formal,
                "history_quality_warning_count": warning,
                "history_quality_warning_share": round(warning / formal, 12),
            }
        )
        rows.append(row)
    return rows


def build_ghost_queue_bundle(
    scoring: pd.DataFrame,
    model: HierarchicalAJ,
    config: OriginJourneyConfig,
) -> dict[str, Any]:
    """Build per-referral estimates using only the already-fixed origin scoring cohort."""
    if scoring["referral_id"].isna().any() or scoring["referral_id"].duplicated().any():
        raise ValueError("scoring referral IDs must be non-null and unique")
    policy = config.ghost_queue
    assignments = model.assignments(scoring)
    rows = []
    for source_row, (raw_tier, _, curve) in zip(scoring.itertuples(index=False), assignments, strict=True):
        waited = float(source_row.days_waited_at_origin)
        observable_end = float(curve.event_times[-1]) if len(curve.event_times) else waited
        p30 = _conditional_state(curve, waited, waited + 30)[0]
        p90, refused90, unresolved90 = _conditional_state(
            curve, waited, waited + policy.admission_probability_horizon_days
        )
        p_ever = _conditional_state(curve, waited, max(waited, observable_end))[0]
        comparable_at_risk = curve.at_risk(waited)
        unsupported = comparable_at_risk < policy.minimum_comparable_at_risk_rows
        degenerate = max(p90, refused90, unresolved90) >= 1 - policy.degeneracy_tolerance
        if unsupported and degenerate:
            reason = "insufficient_and_degenerate_comparable_history"
        elif unsupported:
            reason = "insufficient_comparable_history"
        elif degenerate:
            reason = "degenerate_conditional_distribution"
        else:
            reason = None
        wait_maturity = min(waited / policy.wait_maturity_days, 1.0)
        support = min(comparable_at_risk / policy.minimum_comparable_at_risk_rows, 1.0)
        priority = (1 - p90) * wait_maturity * support
        referral_id = source_row.referral_id
        if isinstance(referral_id, np.integer):
            referral_id = int(referral_id)
        rows.append(
            {
                "referral_id": referral_id,
                "org_code": _text(source_row.org_code),
                "hospital_region_code": _text(source_row.hospital_region_code),
                "profile_code": _text(source_row.profile_code),
                "days_waited_at_origin": int(waited),
                "estimate_tier": TIER_NAMES[raw_tier],
                "observable_curve_end_day": observable_end,
                "comparable_training_at_risk_rows": comparable_at_risk,
                "probability_admitted_within_30d": p30,
                "probability_admitted_within_90d": p90,
                "probability_refused_within_90d": refused90,
                "probability_still_waiting_at_90d": unresolved90,
                "probability_ever_admitted_within_observable_curve": p_ever,
                "verification_priority_score": priority,
                "history_quality_warning": bool(unsupported or degenerate),
                "history_quality_reason_code": reason,
            }
        )
    ranked = sorted(
        rows,
        key=lambda row: (
            -row["verification_priority_score"],
            -row["days_waited_at_origin"],
            str(type(row["referral_id"])),
            str(row["referral_id"]),
        ),
    )
    for rank, row in enumerate(ranked, start=1):
        row["verification_rank"] = rank
    rows.sort(key=lambda row: (str(type(row["referral_id"])), str(row["referral_id"])))
    frame = pd.DataFrame(rows)
    formal = len(rows)
    warning = int(frame["history_quality_warning"].sum()) if formal else 0
    warning_counts = {
        str(reason): int(count)
        for reason, count in frame.loc[frame["history_quality_warning"], "history_quality_reason_code"]
        .value_counts(sort=False)
        .sort_index()
        .items()
    }
    projection = {
        "schema_version": policy.schema_version,
        "publication_id": f"ghost-queue-{config.origin.isoformat()}-v{policy.schema_version}",
        "origin": config.origin.isoformat(),
        "model": "origin-safe hierarchical Aalen-Johansen",
        "estimands": {
            "conditioning": "conditional on remaining unresolved after days_waited_at_origin",
            "probability_admitted_within_30d": "admission cumulative incidence over the next 30 days",
            "probability_admitted_within_90d": "admission cumulative incidence over the next 90 days",
            "probability_ever_admitted_within_observable_curve": (
                "admission cumulative incidence through the last event time in the assigned origin-safe curve"
            ),
        },
        "ranking": {
            "score_name": policy.ranking_score_name,
            "score_formula": policy.ranking_score_formula,
            "higher_score_means": "verify_sooner",
            "wait_maturity_days": policy.wait_maturity_days,
            "minimum_comparable_at_risk_rows": policy.minimum_comparable_at_risk_rows,
            "recommended_history_months": policy.recommended_history_months,
            "tie_breakers": ["days_waited_at_origin_desc", "referral_id_asc"],
            "training_only_justification": policy.ranking_justification,
        },
        "audited_legacy_rule": {
            "minimum_days_waited": policy.minimum_days_waited,
            "admission_probability_horizon_days": policy.admission_probability_horizon_days,
            "admission_probability_strictly_below": policy.admission_probability_threshold,
            "reason_code": policy.rule_reason_code,
            "training_only_justification": policy.training_only_justification,
        },
        "headline": {
            "formal_queue_count": formal,
            "ranked_verification_worklist_count": formal,
            "history_quality_warning_count": warning,
            "history_quality_warning_share": round(warning / formal, 12) if formal else 0.0,
        },
        "history_quality": {
            "warning_reason_counts": warning_counts,
            "ui_message_kk": "мало сопоставимой истории",
        },
        "aggregates": {
            "by_hospital": _aggregate(frame, ["org_code"]),
            "by_region": _aggregate(frame, ["hospital_region_code"]),
            "by_profile": _aggregate(frame, ["profile_code"]),
        },
        "referrals": rows,
        "limitations": [
            "The score orders verification work; it does not declare a referral stale.",
            "The observable history starts on 2025-01-01 and is especially thin for waits of 60 days or more.",
            f"About {policy.recommended_history_months} months of history is needed for real long-wait evidence.",
            "No post-origin outcome is used to create probabilities, warnings, scores, or ranks.",
        ],
    }
    bundle = {
        **projection,
        "publication_identity_sha256": hashlib.sha256(canonical_json_bytes(projection)).hexdigest(),
    }
    validate_ghost_queue_bundle(bundle)
    return bundle


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_all_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_all_keys(item) for item in value), set())
    return set()


def validate_ghost_queue_bundle(bundle: dict[str, Any]) -> None:
    if FORBIDDEN_GHOST_KEYS & _all_keys(bundle):
        raise ValueError("ghost-queue bundle contains hindsight fields")
    projection = dict(bundle)
    supplied = projection.pop("publication_identity_sha256", None)
    expected = hashlib.sha256(canonical_json_bytes(projection)).hexdigest()
    if supplied != expected:
        raise ValueError("ghost-queue identity does not match canonical content")
    referrals = bundle["referrals"]
    ids = [row["referral_id"] for row in referrals]
    if len(ids) != len(set(ids)):
        raise ValueError("ghost-queue referral IDs must be unique")
    ranking = bundle["ranking"]
    for row in referrals:
        probabilities = (
            row["probability_admitted_within_30d"],
            row["probability_admitted_within_90d"],
            row["probability_refused_within_90d"],
            row["probability_still_waiting_at_90d"],
            row["probability_ever_admitted_within_observable_curve"],
        )
        if any(not 0 <= value <= 1 for value in probabilities):
            raise ValueError("ghost-queue probability lies outside [0, 1]")
        if not np.isclose(sum(probabilities[1:4]), 1.0, atol=1e-10):
            raise ValueError("90-day competing probabilities do not sum to one")
        expected_score = (
            (1 - row["probability_admitted_within_90d"])
            * min(row["days_waited_at_origin"] / ranking["wait_maturity_days"], 1.0)
            * min(
                row["comparable_training_at_risk_rows"] / ranking["minimum_comparable_at_risk_rows"],
                1.0,
            )
        )
        if not np.isclose(row["verification_priority_score"], expected_score, atol=1e-12):
            raise ValueError("verification score does not match the precommitted formula")
        if row["history_quality_warning"] != (row["history_quality_reason_code"] is not None):
            raise ValueError("history warning and reason code disagree")
    headline = bundle["headline"]
    if headline["formal_queue_count"] != len(referrals):
        raise ValueError("formal queue does not equal referral rows")
    ranks = sorted(row["verification_rank"] for row in referrals)
    if ranks != list(range(1, len(referrals) + 1)):
        raise ValueError("verification ranks must be unique and contiguous")
    warning = sum(row["history_quality_warning"] for row in referrals)
    if headline["history_quality_warning_count"] != warning:
        raise ValueError("headline history-warning count does not reconcile")
    if sum(bundle["history_quality"]["warning_reason_counts"].values()) != warning:
        raise ValueError("history-warning reason counts do not reconcile")
    for dimension, groups in bundle["aggregates"].items():
        if sum(group["formal_queue_count"] for group in groups) != len(referrals):
            raise ValueError(f"{dimension} formal counts do not sum to the queue")
        if sum(group["history_quality_warning_count"] for group in groups) != warning:
            raise ValueError(f"{dimension} history-warning counts do not reconcile")


def write_ghost_queue_bundle(path: Path, bundle: dict[str, Any]) -> tuple[int, str]:
    validate_ghost_queue_bundle(bundle)
    raw = canonical_json_bytes(bundle) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        path.open("wb") as stream,
        gzip.GzipFile(filename="", mode="wb", fileobj=stream, compresslevel=9, mtime=0) as gz,
    ):
        gz.write(raw)
    payload = path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()
