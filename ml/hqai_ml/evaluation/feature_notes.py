"""Leakage review per feature: when the value becomes known, relative to the prediction time."""

REFERRAL_FEATURES = {
    "region_code": ("A, B", "registration", "part 1 of hospitalization_code, assigned when the referral is created"),
    "org_code": ("A, B", "registration", "receiving hospital chosen in the referral (part 2 of the code)"),
    "hospital_region_code": ("A, B", "static", "dictionary attribute of the hospital (dim_organization), not an outcome"),
    "profile_code": ("A, B", "registration", "bed profile in the referral (part 3 of the code)"),
    "icd_chapter": ("A, B", "registration", "chapter of the referral diagnosis"),
    "icd3": ("A, B", "registration", "3-character referral diagnosis"),
    "referral_purpose": ("A, B", "registration", "referral attribute; assumed not edited after registration"),
    "finance_source": ("A, B", "registration", "referral attribute; assumed not edited after registration"),
    "territorial_type": ("A, B", "registration", "patient city/village flag in the referral"),
    "registration_weekday": ("A, B", "registration", "calendar"),
    "day_of_window": ("A, B", "registration", "days since 2025-01-01; lets the model discount warm-up-biased January aggregates"),
    "queue_hp_prev_day": ("A, B", "end of day d−1", "queue_length of hospital × profile on d−1 (the day before registration), not on d"),
    "hosp_reg_7d": ("A, B", "end of day d−1", "hospital registrations on days d−7 … d−1"),
    "hosp_reg_28d": ("A, B", "end of day d−1", "hospital registrations on days d−28 … d−1"),
    "hosp_hosp_7d": ("A, B", "end of day d−1", "hospitalizations on days d−7 … d−1 (referrals registered since 2025-01-01 only)"),
    "hosp_hosp_28d": ("A, B", "end of day d−1", "hospitalizations on days d−28 … d−1"),
    "hp_median_wait_prev": ("A, B", "end of day d−1", "median wait of non-same-day referrals with hospitalization_date < d (expanding); early dates see only short completed waits"),
    "hp_n_hosp_prev": ("A, B", "end of day d−1", "count behind hp_median_wait_prev"),
    "hp_refusal_rate_prev": ("B", "end of day d−1", "refused / resolved among referrals with resolution_date < d (expanding)"),
    "hp_n_resolved_prev": ("B", "end of day d−1", "count behind hp_refusal_rate_prev"),
    "ersb_throughput_per_day": ("A, B", "static (uncertain)", "ERSB discharged_total / 365; the snapshot has no period and may overlap the test month — mild leakage risk, treated as a slowly changing capacity attribute"),
    "ersb_avg_los": ("A, B", "static (uncertain)", "ERSB bed_days / discharged_total; same caveat as above"),
    "adm_refusals_28d": ("A, B", "end of day d−1", "dataset-3 admission-unit refusals of the hospital on d−28 … d−1"),
    "planned_lag_days": ("excluded (ablation only)", "NOT verifiable", "planned_dt equals the admission date for 81% of hospitalized referrals, is never NULL for them and NULL for 39% of refusals: it is filled or updated when the hospital schedules, after registration"),
}

LOAD_FEATURES = {
    "level, org_code, region_code, profile_code": "series identifiers (static)",
    "horizon": "design variable (1..14)",
    "lag_1, lag_2, lag_3, lag_7, lag_14": "values on days t, t−1, t−2, t−6, t−13 (t = last known day)",
    "roll_mean_7, roll_mean_14, roll_mean_28": "means over the last 7/14/28 days ending on t (NULL if not enough history)",
    "same_weekday_last": "most recent observed value on the target's weekday (≤ t)",
    "queue_at_origin": "queue_length of the series at the end of day t",
    "target_weekday, target_is_holiday, target_day_index": "calendar of the target date, known in advance (holidays from the config)",
}
