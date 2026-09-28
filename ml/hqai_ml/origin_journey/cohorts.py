"""Build model-facing cohorts containing only information available at the origin.

This module is the training import path. It intentionally has no dependency on the
hindsight-label module and never returns a post-origin event date or outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from hqai_ml.origin_journey.config import OriginJourneyConfig

SOURCE_COLUMNS = (
    "referral_id",
    "hospitalization_code",
    "region_code",
    "org_code",
    "hospital_region_code",
    "profile_code",
    "icd10_code",
    "territorial_type",
    "referral_purpose",
    "finance_source",
    "registration_date",
    "hospitalization_date",
    "refusal_date",
)

IDENTITY_COLUMNS = ("referral_id", "hospitalization_code", "registration_date")
REGISTRATION_FEATURE_COLUMNS = (
    "region_code",
    "org_code",
    "hospital_region_code",
    "profile_code",
    "icd10_code",
    "territorial_type",
    "referral_purpose",
    "finance_source",
    "registration_weekday",
    "registration_day_index",
)
TRAINING_LABEL_COLUMNS = (
    "event_type_at_origin",
    "event_observed_at_origin",
    "observed_duration_days",
    "administratively_censored",
    "label_eligible",
    "label_as_of_date",
)


@dataclass(frozen=True)
class OriginCohorts:
    training: pd.DataFrame
    scoring: pd.DataFrame
    audit: dict[str, Any]


def _normalize_source(source: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(SOURCE_COLUMNS) - set(source.columns))
    if missing:
        raise ValueError(f"source columns missing: {missing}")
    work = source[list(SOURCE_COLUMNS)].copy()
    if work["referral_id"].isna().any() or work["referral_id"].duplicated().any():
        raise ValueError("referral_id must be non-null and unique")
    for column in ("registration_date", "hospitalization_date", "refusal_date"):
        parsed = pd.to_datetime(work[column], errors="coerce")
        invalid = work[column].notna() & parsed.isna()
        if invalid.any():
            raise ValueError(f"{column} contains invalid dates")
        work[column] = parsed.dt.normalize()
    if work["registration_date"].isna().any():
        raise ValueError("registration_date must be non-null")
    if work["profile_code"].isna().any():
        raise ValueError("profile_code must be non-null")
    return work.sort_values("referral_id", kind="stable").reset_index(drop=True)


def _registration_view(work: pd.DataFrame, config: OriginJourneyConfig) -> pd.DataFrame:
    result = work[list(IDENTITY_COLUMNS) + list(REGISTRATION_FEATURE_COLUMNS[:-2])].copy()
    result["registration_date"] = result["registration_date"].dt.date
    registration = pd.to_datetime(result["registration_date"])
    result["registration_weekday"] = registration.dt.dayofweek.astype("int8")
    result["registration_day_index"] = (registration - pd.Timestamp(config.history_start)).dt.days.astype("int16")
    return result


def _origin_labels(work: pd.DataFrame, config: OriginJourneyConfig) -> pd.DataFrame:
    origin = pd.Timestamp(config.origin)
    registration = work["registration_date"]
    known_hospitalization = work["hospitalization_date"].notna() & (work["hospitalization_date"] <= origin)
    known_refusal = work["refusal_date"].notna() & (work["refusal_date"] <= origin)
    conflict = known_hospitalization & known_refusal
    has_known_terminal_event = known_hospitalization | known_refusal
    observed = known_hospitalization ^ known_refusal
    event_date = work["hospitalization_date"].where(known_hospitalization, work["refusal_date"])
    event_date = event_date.where(observed)
    earlier_calendar_event = observed & (event_date < registration)
    label_eligible = ~conflict & ~earlier_calendar_event

    event_type = np.select(
        [conflict, known_hospitalization, known_refusal],
        ["conflict", "hospitalized", "refused"],
        default="censored",
    )
    raw_duration = (event_date.fillna(origin) - registration).dt.total_seconds() / 86_400
    duration = raw_duration.clip(lower=0).astype("float64")
    same_day = observed & (duration < config.label_contract.same_day_min_duration_days)
    duration.loc[same_day] = config.label_contract.same_day_min_duration_days

    return pd.DataFrame(
        {
            "event_type_at_origin": pd.Series(event_type, index=work.index, dtype="string"),
            "event_observed_at_origin": observed,
            "observed_duration_days": duration,
            "administratively_censored": ~has_known_terminal_event,
            "label_eligible": label_eligible,
            "label_as_of_date": config.origin,
        },
        index=work.index,
    )


def _wait_distribution(days: pd.Series) -> dict[str, Any]:
    if days.empty:
        return {"count": 0, "buckets": {}}
    bins = [-1, 0, 2, 6, 13, 29, 59, np.inf]
    names = ["0", "1-2", "3-6", "7-13", "14-29", "30-59", "60+"]
    bucket = pd.cut(days, bins=bins, labels=names)
    counts = bucket.value_counts(sort=False)
    return {
        "count": int(len(days)),
        "min": int(days.min()),
        "p25": float(days.quantile(0.25)),
        "median": float(days.median()),
        "p75": float(days.quantile(0.75)),
        "p90": float(days.quantile(0.90)),
        "p95": float(days.quantile(0.95)),
        "max": int(days.max()),
        "mean": float(days.mean()),
        "buckets": {name: int(counts.loc[name]) for name in names},
    }


def build_origin_cohorts(source: pd.DataFrame, config: OriginJourneyConfig) -> OriginCohorts:
    """Construct as-of-origin training and prevalent waiting-list scoring cohorts.

    Raw terminal dates are used only to determine what was already known by end of the
    origin date. They are then omitted. A future hospitalization and a never-resolved
    referral therefore have exactly the same model-facing label at the origin.
    """
    work = _normalize_source(source)
    origin = pd.Timestamp(config.origin)
    excluded = work["profile_code"].isin(config.excluded_profile_codes)
    eligible = (work["registration_date"] <= origin) & ~excluded
    work = work.loc[eligible].reset_index(drop=True)

    features = _registration_view(work, config)
    labels = _origin_labels(work, config)
    training = pd.concat([features, labels], axis=1)
    training = training[list(IDENTITY_COLUMNS) + list(REGISTRATION_FEATURE_COLUMNS) + list(TRAINING_LABEL_COLUMNS)]
    training = training.sort_values("referral_id", kind="stable").reset_index(drop=True)

    waiting = labels["administratively_censored"]
    scoring = features.loc[waiting].copy()
    scoring["days_waited_at_origin"] = (origin - pd.to_datetime(scoring["registration_date"])).dt.days.astype("int16")

    valid_training = training.loc[training["label_eligible"]]
    group_columns = list(config.similar_history.columns)
    support = valid_training.groupby(group_columns, dropna=False, sort=True).size().rename("similar_training_rows")
    scoring = scoring.join(support, on=group_columns)
    scoring["similar_training_rows"] = scoring["similar_training_rows"].fillna(0).astype("int32")
    scoring["has_similar_training_history"] = scoring["similar_training_rows"] >= config.similar_history.min_rows
    scoring = scoring.sort_values("referral_id", kind="stable").reset_index(drop=True)

    censored = int(training["administratively_censored"].sum())
    audit = {
        "schema_version": config.schema_version,
        "origin": config.origin.isoformat(),
        "day_hospital_excluded": list(config.excluded_profile_codes),
        "training_rows": int(len(training)),
        "training_label_eligible_rows": int(training["label_eligible"].sum()),
        "training_administratively_censored_rows": censored,
        "training_censoring_share": censored / len(training) if len(training) else 0.0,
        "scoring_rows": int(len(scoring)),
        "scoring_supported_rows": int(scoring["has_similar_training_history"].sum()),
        "scoring_support_share": float(scoring["has_similar_training_history"].mean()) if len(scoring) else 0.0,
        "similar_history_min_rows": config.similar_history.min_rows,
        "days_waited_at_origin": _wait_distribution(scoring["days_waited_at_origin"]),
    }
    return OriginCohorts(training=training, scoring=scoring, audit=audit)
