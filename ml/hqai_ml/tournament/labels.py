from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from hqai_ml.tournament.config import LabelContract

DAY_SECONDS = 86_400
EVENT_CENSORED = 0
EVENT_HOSPITALIZED = 1
EVENT_REFUSED = 2


@dataclass(frozen=True)
class LabelResult:
    rows: pd.DataFrame
    audit: dict


def _cohort_breakdown(work: pd.DataFrame, invalid: pd.Series, strict_invalid: pd.Series) -> dict[str, list[dict]]:
    """Report main/strict cohort shares without hiding small source groups."""
    result = {}
    for output_name, column in (
        ("hospital", "org_code"),
        ("profile", "profile_code"),
        ("purpose", "referral_purpose"),
    ):
        if column not in work:
            continue
        grouped = pd.DataFrame(
            {
                "segment": work[column].astype("string").fillna("<missing>"),
                "excluded": invalid.to_numpy(bool),
                "strict_excluded": strict_invalid.to_numpy(bool),
            }
        ).groupby("segment", dropna=False, sort=True)
        rows = []
        for segment, group in grouped:
            n = len(group)
            excluded = int(group["excluded"].sum())
            strict_excluded = int(group["strict_excluded"].sum())
            rows.append(
                {
                    "segment": str(segment),
                    "input_rows": n,
                    "eligible_rows": n - excluded,
                    "excluded_rows": excluded,
                    "exclusion_share": excluded / n,
                    "strict_eligible_rows": n - strict_excluded,
                    "strict_excluded_rows": strict_excluded,
                    "strict_exclusion_share": strict_excluded / n,
                }
            )
        result[output_name] = rows
    return result


def construct_journey_labels(df: pd.DataFrame, contract: LabelContract) -> LabelResult:
    """Create fixed-cutoff survival labels and retain explicit exclusion reasons."""
    work = df.copy()
    start = pd.to_datetime(work[contract.start], errors="coerce")
    hospitalized = pd.to_datetime(work["hospitalization_dt"], errors="coerce")
    refused = pd.to_datetime(work["refusal_dt"], errors="coerce")
    cutoff = pd.Timestamp(contract.cutoff)
    if cutoff.tz is not None:
        cutoff = cutoff.tz_localize(None)

    conflict = hospitalized.notna() & refused.notna()
    event_time = hospitalized.where(hospitalized.notna(), refused)
    event_type = np.select(
        [hospitalized.notna() & refused.isna(), refused.notna() & hospitalized.isna()],
        [EVENT_HOSPITALIZED, EVENT_REFUSED],
        default=EVENT_CENSORED,
    ).astype("int8")
    after_cutoff = event_time.notna() & (event_time >= cutoff)
    event_time = event_time.mask(after_cutoff)
    event_type = np.where(after_cutoff, EVENT_CENSORED, event_type).astype("int8")
    end = event_time.fillna(cutoff)
    raw_duration = (end - start).dt.total_seconds() / DAY_SECONDS
    missing_start = start.isna()
    # Source timestamps have time-of-day disagreements on otherwise valid same-day
    # journeys.  The principal cohort excludes only impossible earlier *dates*;
    # exact timestamp order is retained as a named sensitivity cohort.
    timestamp_before_start = event_time.notna() & (event_time < start)
    earlier_calendar_date = timestamp_before_start & (event_time.dt.normalize() < start.dt.normalize())
    same_calendar_pre_registration = timestamp_before_start & ~earlier_calendar_date
    invalid = missing_start.copy()
    if contract.exclude_event_conflicts:
        invalid |= conflict
    if contract.exclude_events_before_registration:
        invalid |= earlier_calendar_date

    strict_invalid = invalid | timestamp_before_start

    reason = np.full(len(work), None, dtype=object)
    reason[missing_start] = "missing_registration"
    reason[conflict & pd.isna(reason)] = "conflicting_terminal_events"
    reason[earlier_calendar_date & pd.isna(reason)] = "event_on_earlier_calendar_date"
    valid = ~invalid
    model_duration = raw_duration.clip(lower=contract.same_day_min_duration_days)
    work["journey_event"] = event_type
    work["journey_duration_days"] = model_duration.astype(float)
    work["journey_raw_duration_days"] = raw_duration.astype(float)
    work["journey_exclusion_reason"] = reason
    work["journey_label_cutoff"] = cutoff
    work["journey_strict_timestamp_eligible"] = ~strict_invalid
    work["journey_same_calendar_pre_registration"] = same_calendar_pre_registration

    valid_rows = work[valid].copy().reset_index(drop=True)
    audit = {
        "input_rows": int(len(work)),
        "eligible_rows": int(valid.sum()),
        "excluded_rows": int(invalid.sum()),
        "exclusion_reasons": {
            str(key): int(value) for key, value in pd.Series(reason[invalid]).value_counts().sort_index().items()
        },
        "event_counts": {
            "censored": int((valid_rows["journey_event"] == EVENT_CENSORED).sum()),
            "hospitalized": int((valid_rows["journey_event"] == EVENT_HOSPITALIZED).sum()),
            "refused": int((valid_rows["journey_event"] == EVENT_REFUSED).sum()),
        },
        "same_day_adjusted": int(
            (
                (valid_rows["journey_event"] != EVENT_CENSORED)
                & (valid_rows["journey_raw_duration_days"] < contract.same_day_min_duration_days)
            ).sum()
        ),
        "same_calendar_pre_registration_included": int((same_calendar_pre_registration & valid).sum()),
        "strict_timestamp_order_sensitivity": {
            "eligible_rows": int((~strict_invalid).sum()),
            "excluded_rows": int(strict_invalid.sum()),
            "additional_exclusions_vs_main": int((strict_invalid & ~invalid).sum()),
        },
        "events_hidden_after_cutoff": int(after_cutoff.sum()),
        "duplicate_code_rows": int(work.get("is_dup_code", pd.Series(False, index=work.index)).fillna(False).sum()),
        "cutoff": cutoff.isoformat(),
        "cohort_by_dimension": _cohort_breakdown(work, invalid, strict_invalid),
    }
    return LabelResult(valid_rows, audit)


def aft_bounds(labels: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Hospitalization AFT bounds: refusal/open are right-censored, never fake completed waits."""
    lower = labels["journey_duration_days"].to_numpy(float)
    upper = lower.copy()
    upper[labels["journey_event"].to_numpy() != EVENT_HOSPITALIZED] = np.inf
    return lower, upper


def split_by_period(df: pd.DataFrame, period: tuple[dt.date, dt.date]) -> pd.DataFrame:
    dates = pd.to_datetime(df["registration_date"]).dt.date
    return df[(dates >= period[0]) & (dates <= period[1])].copy().reset_index(drop=True)


def recensor_at(labels: pd.DataFrame, cutoff: dt.date | dt.datetime | pd.Timestamp) -> pd.DataFrame:
    """Create a deployment-realistic view containing only outcomes known by ``cutoff``."""
    result = labels.copy()
    cutoff_ts = pd.Timestamp(cutoff)
    start = pd.to_datetime(result["registration_dt"], errors="coerce")
    known_duration = (cutoff_ts - start).dt.total_seconds() / DAY_SECONDS
    after = result["journey_duration_days"].to_numpy(float) > known_duration.to_numpy(float)
    result.loc[after, "journey_event"] = EVENT_CENSORED
    result.loc[after, "journey_duration_days"] = known_duration[after].clip(lower=0).to_numpy(float)
    result["journey_historical_cutoff"] = cutoff_ts
    return result
