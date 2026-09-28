"""Hindsight labels for evaluation only.

This module is intentionally absent from ``origin_journey.__all__`` and is not imported
by the training cohort path. Consumers must opt into hindsight explicitly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hqai_ml.origin_journey.config import OriginJourneyConfig

EVALUATION_COLUMNS = (
    "referral_id",
    "evaluation_event_type",
    "evaluation_event_date",
    "days_from_origin",
    "evaluation_label_eligible",
    "evaluation_cutoff_exclusive",
)


def build_evaluation_labels(
    source: pd.DataFrame,
    scoring_referral_ids: pd.Series,
    config: OriginJourneyConfig,
) -> pd.DataFrame:
    """Build eventual labels only for the already-fixed scoring cohort.

    The explicit ID input prevents this function from silently redefining the scoring
    cohort. Events at or after the exclusive cutoff remain censored and undisclosed.
    """
    required = {"referral_id", "hospitalization_date", "refusal_date"}
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"source columns missing: {missing}")
    ids = pd.Series(scoring_referral_ids, copy=True)
    if ids.isna().any() or ids.duplicated().any():
        raise ValueError("scoring_referral_ids must be non-null and unique")
    selected = source.loc[source["referral_id"].isin(ids), list(required)].copy()
    if len(selected) != len(ids) or set(selected["referral_id"]) != set(ids):
        raise ValueError("every scoring referral ID must occur exactly once in source")
    for column in ("hospitalization_date", "refusal_date"):
        parsed = pd.to_datetime(selected[column], errors="coerce")
        if (selected[column].notna() & parsed.isna()).any():
            raise ValueError(f"{column} contains invalid dates")
        selected[column] = parsed.dt.normalize()

    origin = pd.Timestamp(config.origin)
    cutoff = pd.Timestamp(config.outcome_cutoff)
    hospitalization = selected["hospitalization_date"]
    refusal = selected["refusal_date"]
    known_hospitalization = hospitalization.notna() & (hospitalization > origin) & (hospitalization < cutoff)
    known_refusal = refusal.notna() & (refusal > origin) & (refusal < cutoff)
    conflict = known_hospitalization & known_refusal
    observed = known_hospitalization ^ known_refusal
    event_date = hospitalization.where(known_hospitalization, refusal).where(observed)
    event_type = np.select(
        [conflict, known_hospitalization, known_refusal],
        ["conflict", "hospitalized", "refused"],
        default="censored",
    )
    days = (event_date.fillna(cutoff) - origin).dt.total_seconds() / 86_400
    labels = pd.DataFrame(
        {
            "referral_id": selected["referral_id"],
            "evaluation_event_type": pd.Series(event_type, index=selected.index, dtype="string"),
            "evaluation_event_date": event_date.dt.date,
            "days_from_origin": days.astype("float64"),
            "evaluation_label_eligible": ~conflict,
            "evaluation_cutoff_exclusive": config.outcome_cutoff,
        }
    )
    return labels[list(EVALUATION_COLUMNS)].sort_values("referral_id", kind="stable").reset_index(drop=True)


def _reliability(y: np.ndarray, probability: np.ndarray, bins: int) -> list[dict]:
    if len(y) == 0:
        return []
    order = np.argsort(probability, kind="stable")
    rows = []
    for index, indexes in enumerate(np.array_split(order, min(bins, len(order)))):
        if len(indexes) == 0:
            continue
        values = probability[indexes]
        rows.append(
            {
                "bin": index,
                "n": int(len(indexes)),
                "probability_min": float(values.min()),
                "probability_max": float(values.max()),
                "mean_predicted": float(values.mean()),
                "observed_rate": float(y[indexes].mean()),
            }
        )
    return rows


def _slice_metrics(
    outcomes: np.ndarray,
    days_from_origin: np.ndarray,
    probabilities: dict[int, dict[str, np.ndarray]],
    horizons: tuple[int, ...],
    indexes: np.ndarray,
    reliability_bins: int,
) -> dict:
    by_horizon = {}
    brier_values = []
    for horizon in horizons:
        horizon_rows = {}
        for cause in ("hospitalized", "refused"):
            probability = np.asarray(probabilities[horizon][cause], dtype=float)[indexes]
            target = ((outcomes[indexes] == cause) & (days_from_origin[indexes] <= horizon)).astype(float)
            brier = float(np.mean((probability - target) ** 2))
            brier_values.append(brier)
            horizon_rows[cause] = {
                "brier": brier,
                "mean_predicted": float(probability.mean()),
                "observed_rate": float(target.mean()),
                "reliability": _reliability(target, probability, reliability_bins),
            }
        coherence = sum(
            np.asarray(probabilities[horizon][cause], dtype=float)[indexes] for cause in probabilities[horizon]
        )
        horizon_rows["coherence_max_abs_error"] = float(np.max(np.abs(coherence - 1)))
        by_horizon[str(horizon)] = horizon_rows
    return {
        "n": int(len(indexes)),
        "mean_admission_and_refusal_brier": float(np.mean(brier_values)),
        "by_horizon": by_horizon,
    }


def _wait_bucket(days: pd.Series) -> pd.Series:
    return pd.cut(
        days,
        bins=[-1, 0, 6, 13, 29, 59, np.inf],
        labels=["0", "1-6", "7-13", "14-29", "30-59", "60+"],
    ).astype("string")


def evaluate_predictions(
    labels: pd.DataFrame,
    scoring: pd.DataFrame,
    prediction_sets: dict[str, dict[int, dict[str, np.ndarray]]],
    config: OriginJourneyConfig,
) -> dict:
    """Evaluate predictions; this is the only origin-journey path that consumes hindsight labels."""
    if not labels["referral_id"].equals(scoring["referral_id"]):
        raise ValueError("evaluation labels and scoring rows must have identical referral ordering")
    eligible = labels["evaluation_label_eligible"].to_numpy(bool)
    outcomes = labels["evaluation_event_type"].astype(str).to_numpy()
    days_from_origin = labels["days_from_origin"].to_numpy(float)
    wait_buckets = _wait_bucket(scoring["days_waited_at_origin"])
    regions = scoring[config.evaluation.region_column].astype("string").fillna("<missing>")
    support = scoring["has_similar_training_history"].map({True: "supported", False: "low_support"})
    dimensions = {
        "days_waited": wait_buckets,
        "region": regions,
        "support": support,
    }
    result = {}
    for model_name, probabilities in prediction_sets.items():
        model_result = {
            "overall": _slice_metrics(
                outcomes,
                days_from_origin,
                probabilities,
                config.horizons,
                np.flatnonzero(eligible),
                config.evaluation.reliability_bins,
            ),
            "subgroups": {},
        }
        for dimension, values in dimensions.items():
            groups = {}
            for value in sorted(values.dropna().unique()):
                indexes = np.flatnonzero(eligible & (values.to_numpy() == value))
                if len(indexes):
                    groups[str(value)] = _slice_metrics(
                        outcomes,
                        days_from_origin,
                        probabilities,
                        config.horizons,
                        indexes,
                        config.evaluation.reliability_bins,
                    )
            model_result["subgroups"][dimension] = groups
        result[model_name] = model_result
    return result


def apply_decision_rule(metrics: dict, config: OriginJourneyConfig) -> dict:
    baseline_name = config.decision.fallback
    baseline = metrics[baseline_name]
    tolerance = config.decision.max_days_waited_bucket_degradation
    candidates = {}
    for candidate in config.decision.product_priority:
        candidate_metrics = metrics[candidate]
        overall = candidate_metrics["overall"]["mean_admission_and_refusal_brier"]
        baseline_overall = baseline["overall"]["mean_admission_and_refusal_brier"]
        bucket_deltas = {}
        for bucket, candidate_bucket in candidate_metrics["subgroups"]["days_waited"].items():
            baseline_bucket = baseline["subgroups"]["days_waited"][bucket]
            bucket_deltas[bucket] = (
                candidate_bucket["mean_admission_and_refusal_brier"]
                - baseline_bucket["mean_admission_and_refusal_brier"]
            )
        strict_improvement = overall < baseline_overall
        within_tolerance = max(bucket_deltas.values(), default=float("inf")) <= tolerance
        candidates[candidate] = {
            "accepted": bool(strict_improvement and within_tolerance),
            "overall_mean_brier": overall,
            "baseline_overall_mean_brier": baseline_overall,
            "overall_delta": overall - baseline_overall,
            "days_waited_bucket_deltas": bucket_deltas,
            "worst_bucket_delta": max(bucket_deltas.values(), default=None),
            "tolerance": tolerance,
            "strict_overall_improvement": strict_improvement,
            "within_bucket_tolerance": within_tolerance,
        }
    selected = next(
        (candidate for candidate in config.decision.product_priority if candidates[candidate]["accepted"]),
        baseline_name,
    )
    return {
        "precommitted_metric": config.decision.metric,
        "selected_model": selected,
        "fallback_used": selected == baseline_name,
        "candidate_decisions": candidates,
    }


def _citizen_evaluation_row(group: pd.DataFrame) -> dict:
    valid_admission = group["valid_admission"].fillna(False).to_numpy(bool)
    actual = group["actual_admission_days"].to_numpy(float)
    median = group["median_days_to_admission"].to_numpy(float)
    p80 = group["admitted_80pct_by_day"].to_numpy(float)
    median_evaluable = valid_admission & np.isfinite(median)
    p80_evaluable = valid_admission & np.isfinite(p80)
    median_hits = median_evaluable & (actual <= median)
    p80_hits = p80_evaluable & (actual <= p80)
    return {
        "registered_referrals": int(len(group)),
        "valid_admissions": int(valid_admission.sum()),
        "median_evaluable_admissions": int(median_evaluable.sum()),
        "admitted_by_median": int(median_hits.sum()),
        "admitted_by_median_share": (
            float(median_hits.sum() / median_evaluable.sum()) if median_evaluable.any() else None
        ),
        "p80_evaluable_admissions": int(p80_evaluable.sum()),
        "admitted_by_p80": int(p80_hits.sum()),
        "admitted_by_p80_share": float(p80_hits.sum() / p80_evaluable.sum()) if p80_evaluable.any() else None,
    }


def evaluate_citizen_wait_bundle(
    bundle: dict,
    source: pd.DataFrame,
    config: OriginJourneyConfig,
) -> dict:
    """Evaluate public incident-referral estimates; only this hindsight module reads eventual outcomes."""
    required = {
        "referral_id",
        "org_code",
        "profile_code",
        "registration_date",
        "hospitalization_date",
        "refusal_date",
    }
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"source columns missing: {missing}")
    work = source[list(required)].copy()
    for column in ("registration_date", "hospitalization_date", "refusal_date"):
        parsed = pd.to_datetime(work[column], errors="coerce")
        if (work[column].notna() & parsed.isna()).any():
            raise ValueError(f"{column} contains invalid dates")
        work[column] = parsed.dt.normalize()
    start, end = config.citizen_wait.evaluation_registration_period
    inside = work["registration_date"].dt.date.between(start, end)
    non_day_hospital = ~work["profile_code"].isin(config.excluded_profile_codes)
    work = work.loc[inside & non_day_hospital].copy()

    cells = pd.DataFrame(bundle["cells"])[
        [
            "org_code",
            "profile_code",
            "estimate_tier",
            "median_days_to_admission",
            "admitted_80pct_by_day",
        ]
    ]
    work = work.merge(cells, on=["org_code", "profile_code"], how="left", validate="many_to_one")
    cutoff = pd.Timestamp(config.outcome_cutoff)
    conflict = work["hospitalization_date"].notna() & work["refusal_date"].notna()
    known_admission = work["hospitalization_date"].notna() & (work["hospitalization_date"] < cutoff)
    event_not_before_registration = work["hospitalization_date"] >= work["registration_date"]
    work["valid_admission"] = known_admission & ~conflict & event_not_before_registration
    work["actual_admission_days"] = (
        work["hospitalization_date"] - work["registration_date"]
    ).dt.total_seconds() / 86_400
    work["estimate_tier"] = work["estimate_tier"].fillna("unpublished_cell")

    by_tier = {
        str(tier): _citizen_evaluation_row(group)
        for tier, group in work.groupby("estimate_tier", sort=True, dropna=False)
    }
    return {
        "registration_period": [start.isoformat(), end.isoformat()],
        "denominator": "valid eventual admissions with a non-null published quantile",
        "overall": _citizen_evaluation_row(work),
        "by_support_tier": by_tier,
        "unpublished_referrals": int((work["estimate_tier"] == "unpublished_cell").sum()),
    }


def _ghost_metrics(group: pd.DataFrame) -> dict:
    eligible = group["evaluation_eligible"].to_numpy(bool)
    flagged = group["likely_stale"].to_numpy(bool) & eligible
    ghosts = group["actual_ghost"].to_numpy(bool) & eligible
    true_positive = flagged & ghosts
    return {
        "referrals": int(len(group)),
        "evaluation_eligible": int(eligible.sum()),
        "flagged": int(flagged.sum()),
        "actual_ghosts": int(ghosts.sum()),
        "true_positive": int(true_positive.sum()),
        "false_positive_admitted": int((flagged & ~ghosts).sum()),
        "precision": float(true_positive.sum() / flagged.sum()) if flagged.any() else None,
        "recall": float(true_positive.sum() / ghosts.sum()) if ghosts.any() else None,
        "refused_ghosts": int((group["known_refusal"].to_numpy(bool) & eligible).sum()),
        "still_waiting_at_cutoff": int((group["still_waiting_at_cutoff"].to_numpy(bool) & eligible).sum()),
        "flagged_refused": int((flagged & group["known_refusal"].to_numpy(bool)).sum()),
        "flagged_still_waiting": int((flagged & group["still_waiting_at_cutoff"].to_numpy(bool)).sum()),
    }


def _flag_calibration(group: pd.DataFrame) -> dict:
    flagged = group["legacy_flag"].to_numpy(bool) & group["evaluation_eligible"].to_numpy(bool)
    admitted_90 = group["admitted_within_90d_after_origin"].to_numpy(bool) & flagged
    return {
        "flagged": int(flagged.sum()),
        "mean_model_probability_admitted_90d": (
            float(group.loc[flagged, "probability_admitted_within_90d"].mean()) if flagged.any() else None
        ),
        "admitted_within_90d": int(admitted_90.sum()),
        "observed_admitted_within_90d_share": (float(admitted_90.sum() / flagged.sum()) if flagged.any() else None),
    }


def _yield_row(group: pd.DataFrame, base_rate: float) -> dict:
    eligible = group["evaluation_eligible"].to_numpy(bool)
    ghosts = group["actual_ghost"].to_numpy(bool) & eligible
    evaluated = int(eligible.sum())
    yield_share = float(ghosts.sum() / evaluated) if evaluated else None
    return {
        "selected": int(len(group)),
        "evaluation_eligible": evaluated,
        "true_ghosts": int(ghosts.sum()),
        "yield": yield_share,
        "lift_vs_base": float(yield_share / base_rate) if yield_share is not None and base_rate else None,
    }


def _fact_rows(work: pd.DataFrame, column: str) -> list[dict]:
    rows = []
    for value, group in work.groupby(column, sort=True, dropna=False):
        eligible = group["evaluation_eligible"].to_numpy(bool)
        rows.append(
            {
                column: "<missing>" if pd.isna(value) else str(value),
                "origin_waiters": int(eligible.sum()),
                "later_refused": int((group["known_refusal"].to_numpy(bool) & eligible).sum()),
                "still_open_at_cutoff": int((group["still_waiting_at_cutoff"].to_numpy(bool) & eligible).sum()),
            }
        )
    return rows


def evaluate_ghost_queue_bundle(bundle: dict, source: pd.DataFrame, config: OriginJourneyConfig) -> dict:
    """Evaluate frozen ghost flags; this isolated path alone reads post-origin outcomes."""
    required = {"referral_id", "hospitalization_date", "refusal_date"}
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"source columns missing: {missing}")
    public_columns = [
        "referral_id",
        "hospital_region_code",
        "profile_code",
        "days_waited_at_origin",
        "estimate_tier",
        "probability_admitted_within_90d",
        "verification_rank",
    ]
    public = pd.DataFrame(bundle["referrals"])[public_columns]
    if public["referral_id"].duplicated().any():
        raise ValueError("bundle referral IDs must be unique")
    selected = source.loc[source["referral_id"].isin(public["referral_id"]), list(required)].copy()
    if len(selected) != len(public) or set(selected["referral_id"]) != set(public["referral_id"]):
        raise ValueError("every bundled referral must occur exactly once in source")
    for column in ("hospitalization_date", "refusal_date"):
        parsed = pd.to_datetime(selected[column], errors="coerce")
        if (selected[column].notna() & parsed.isna()).any():
            raise ValueError(f"{column} contains invalid dates")
        selected[column] = parsed.dt.normalize()
    work = public.merge(selected, on="referral_id", how="left", validate="one_to_one")
    origin = pd.Timestamp(config.origin)
    cutoff = pd.Timestamp(config.outcome_cutoff)
    work["known_admission"] = (
        work["hospitalization_date"].notna()
        & (work["hospitalization_date"] > origin)
        & (work["hospitalization_date"] < cutoff)
    )
    work["known_refusal"] = (
        work["refusal_date"].notna() & (work["refusal_date"] > origin) & (work["refusal_date"] < cutoff)
    )
    work["evaluation_eligible"] = ~(work["known_admission"] & work["known_refusal"])
    work["still_waiting_at_cutoff"] = ~work["known_admission"] & ~work["known_refusal"]
    work["actual_ghost"] = ~work["known_admission"] & (work["known_refusal"] | work["still_waiting_at_cutoff"])
    legacy = bundle["audited_legacy_rule"]
    work["legacy_flag"] = (work["days_waited_at_origin"] >= legacy["minimum_days_waited"]) & (
        work["probability_admitted_within_90d"] < legacy["admission_probability_strictly_below"]
    )
    work["likely_stale"] = work["legacy_flag"]  # evaluation-only compatibility with the B5 audit metric
    work["admitted_within_90d_after_origin"] = work["known_admission"] & (
        work["hospitalization_date"] <= origin + pd.Timedelta(days=legacy["admission_probability_horizon_days"])
    )
    work["days_waited_bucket"] = _wait_bucket(work["days_waited_at_origin"])

    wait_labels = ["0", "1-6", "7-13", "14-29", "30-59", "60+"]
    tier_labels = sorted(work["estimate_tier"].dropna().astype(str).unique())
    calibration = {
        "claim": (
            f"conditional admission probability within {legacy['admission_probability_horizon_days']} days "
            f"is below {legacy['admission_probability_strictly_below']:.0%}"
        ),
        "observed_outcome": "admitted within 90 days after the origin",
        "overall": _flag_calibration(work),
        "by_days_waited_bucket": {
            bucket: _flag_calibration(work.loc[work["days_waited_bucket"] == bucket]) for bucket in wait_labels
        },
        "by_support_tier": {
            tier: _flag_calibration(work.loc[work["estimate_tier"].astype(str) == tier]) for tier in tier_labels
        },
    }

    eligible = work["evaluation_eligible"].to_numpy(bool)
    ghosts = work["actual_ghost"].to_numpy(bool) & eligible
    base_rate = float(ghosts.sum() / eligible.sum())
    work["region_key"] = work["hospital_region_code"].astype("string").fillna("<missing>").astype(str)
    ranked = work.sort_values("verification_rank", kind="stable")
    points = {}
    by_region: dict[str, dict] = {}
    for region, group in work.groupby("region_key", sort=True, dropna=False):
        region_eligible = group["evaluation_eligible"].to_numpy(bool)
        region_ghosts = group["actual_ghost"].to_numpy(bool) & region_eligible
        region_base = float(region_ghosts.sum() / region_eligible.sum()) if region_eligible.any() else 0.0
        by_region[str(region)] = {
            "base_rate": region_base,
            "origin_waiters": int(region_eligible.sum()),
            "points": {},
        }
    for cutoff in config.ghost_queue.yield_cutoffs:
        selected = ranked.head(cutoff)
        points[str(cutoff)] = _yield_row(selected, base_rate)
        for region, result in by_region.items():
            group = selected.loc[selected["region_key"] == region]
            result["points"][str(cutoff)] = _yield_row(group, result["base_rate"])

    return {
        "cutoff_exclusive": config.outcome_cutoff.isoformat(),
        "ghost_definition": "no admission before cutoff: refused or still waiting at cutoff",
        "base_rate": base_rate,
        "legacy_flag_outcomes": _ghost_metrics(work),
        "flag_claim_calibration": calibration,
        "yield_curve": points,
        "yield_curve_by_region": by_region,
        "hindsight_fact_block": {
            "evaluation_only_not_model_output": True,
            "overall": {
                "origin_waiters": int(eligible.sum()),
                "later_refused": int((work["known_refusal"].to_numpy(bool) & eligible).sum()),
                "still_open_at_cutoff": int((work["still_waiting_at_cutoff"].to_numpy(bool) & eligible).sum()),
            },
            "by_region": _fact_rows(work, "hospital_region_code"),
            "by_profile": _fact_rows(work, "profile_code"),
        },
    }
