"""Referral-level features for Models A (wait time) and B (refusal risk).

Every feature uses only information available at the START of the registration date d:
aggregates are taken up to d-1 inclusive, and label-derived statistics use only referrals
whose outcome happened strictly before d. Per-feature leakage notes: docs/model_card.md.
"""

import datetime as dt

import duckdb
import pandas as pd

from hqai_ml.features.icd import icd3, icd_chapter

CATEGORICAL = [
    "region_code",  # patient's region of origin (hospitalization_code part 1)
    "org_code",  # receiving hospital
    "hospital_region_code",  # hospital's own region
    "profile_code",
    "icd_chapter",
    "icd3",
    "referral_purpose",
    "finance_source",
    "territorial_type",
]
NUMERIC = [
    "registration_weekday",
    "day_of_window",
    "queue_hp_prev_day",
    "hosp_reg_7d",
    "hosp_reg_28d",
    "hosp_hosp_7d",
    "hosp_hosp_28d",
    "hp_median_wait_prev",
    "hp_n_hosp_prev",
    "ersb_throughput_per_day",
    "ersb_avg_los",
    "adm_refusals_28d",
]
REFUSAL_EXTRA = ["hp_refusal_rate_prev", "hp_n_resolved_prev"]
# Excluded from the main models: planned_dt is very likely filled/updated after registration
# (equals the admission date for 81% of hospitalized referrals, NULL only for refusals).
# Used only in the ablation that quantifies what it would add.
SUSPECTED_LEAK = ["planned_lag_days"]

LABEL_COLUMNS = ["referral_id", "registration_date", "outcome", "same_day_registration", "wait_days"]


def build_referral_features(con: duckdb.DuckDBPyConnection, window_start: dt.date) -> pd.DataFrame:
    p = {"start": window_start}
    # hospital daily totals over all profiles (the aggregate grid is dense per hospital x profile)
    con.execute("""CREATE OR REPLACE TEMP TABLE _org_daily AS
                   SELECT date, org_code, sum(registrations) AS reg, sum(hospitalizations) AS hosp
                   FROM agg_daily_hospital_profile GROUP BY ALL""")
    con.execute("""CREATE OR REPLACE TEMP TABLE _org_roll AS
                   SELECT date, org_code,
                          sum(reg)  OVER w7  AS hosp_reg_7d,  sum(reg)  OVER w28 AS hosp_reg_28d,
                          sum(hosp) OVER w7  AS hosp_hosp_7d, sum(hosp) OVER w28 AS hosp_hosp_28d
                   FROM _org_daily
                   WINDOW w7  AS (PARTITION BY org_code ORDER BY date ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING),
                          w28 AS (PARTITION BY org_code ORDER BY date ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING)""")
    # admission-unit refusals (dataset 3) in the previous 28 days; NULL for hospitals absent from dataset 3
    con.execute("""CREATE OR REPLACE TEMP TABLE _adm_roll AS
                   WITH present AS (SELECT DISTINCT org_code FROM agg_daily_admission_refusals),
                   grid AS (SELECT d.date, d.org_code, coalesce(a.refusals, 0) AS n
                            FROM _org_daily d JOIN present USING (org_code)
                            LEFT JOIN agg_daily_admission_refusals a USING (date, org_code))
                   SELECT date, org_code,
                          sum(n) OVER (PARTITION BY org_code ORDER BY date
                                       ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING) AS adm_refusals_28d
                   FROM grid""")
    # expanding hospital x profile statistics from outcomes strictly before each registration date
    con.execute("""CREATE OR REPLACE TEMP TABLE _hp_wait AS
                   WITH h AS (SELECT org_code, profile_code, hospitalization_date AS d, wait_days
                              FROM fact_referral WHERE outcome = 'hospitalized' AND NOT same_day_registration),
                   dates AS (SELECT DISTINCT registration_date AS d FROM fact_referral)
                   SELECT dates.d AS registration_date, h.org_code, h.profile_code,
                          median(h.wait_days) AS hp_median_wait_prev, count(*) AS hp_n_hosp_prev
                   FROM dates JOIN h ON h.d < dates.d GROUP BY ALL""")
    con.execute("""CREATE OR REPLACE TEMP TABLE _hp_refusal AS
                   WITH r AS (SELECT org_code, profile_code, resolution_date AS d, count(*) AS n,
                                     count(*) FILTER (WHERE outcome = 'refused') AS n_refused
                              FROM fact_referral WHERE resolution_date IS NOT NULL GROUP BY ALL),
                   dates AS (SELECT DISTINCT registration_date AS d FROM fact_referral)
                   SELECT dates.d AS registration_date, r.org_code, r.profile_code,
                          sum(r.n_refused) / sum(r.n) AS hp_refusal_rate_prev, sum(r.n) AS hp_n_resolved_prev
                   FROM dates JOIN r ON r.d < dates.d GROUP BY ALL""")

    df = con.execute(
        """SELECT f.referral_id, f.registration_date, f.outcome, f.same_day_registration, f.wait_days,
                  f.region_code, f.org_code, f.hospital_region_code, f.profile_code, f.icd10_code,
                  f.referral_purpose, f.finance_source, f.territorial_type,
                  CAST(f.registration_weekday AS INTEGER) AS registration_weekday,
                  CAST(date_diff('day', $start, f.registration_date) AS INTEGER) AS day_of_window,
                  q.queue_length AS queue_hp_prev_day,
                  r.hosp_reg_7d, r.hosp_reg_28d, r.hosp_hosp_7d, r.hosp_hosp_28d,
                  w.hp_median_wait_prev, w.hp_n_hosp_prev,
                  x.hp_refusal_rate_prev, x.hp_n_resolved_prev,
                  e.discharged_total / 365.0 AS ersb_throughput_per_day,
                  e.avg_length_of_stay AS ersb_avg_los,
                  a.adm_refusals_28d,
                  f.planned_lag_days
           FROM fact_referral f
           LEFT JOIN agg_daily_hospital_profile q
                  ON q.org_code = f.org_code AND q.profile_code = f.profile_code
                 AND q.date = f.registration_date - INTERVAL 1 DAY
           LEFT JOIN _org_roll r ON r.org_code = f.org_code AND r.date = f.registration_date
           LEFT JOIN _hp_wait w ON w.org_code = f.org_code AND w.profile_code = f.profile_code
                                AND w.registration_date = f.registration_date
           LEFT JOIN _hp_refusal x ON x.org_code = f.org_code AND x.profile_code = f.profile_code
                                   AND x.registration_date = f.registration_date
           LEFT JOIN dim_organization o ON o.org_code = f.org_code
           LEFT JOIN ersb_snapshot e ON e.ersb_id = o.ersb_id
           LEFT JOIN _adm_roll a ON a.org_code = f.org_code AND a.date = f.registration_date
           ORDER BY f.referral_id""",
        p,
    ).df()

    codes = pd.Series(df["icd10_code"].unique())
    df["icd3"] = df["icd10_code"].map(dict(zip(codes, codes.map(icd3), strict=True)))
    df["icd_chapter"] = df["icd10_code"].map(dict(zip(codes, codes.map(icd_chapter), strict=True)))
    df = df.drop(columns=["icd10_code"])
    df["registration_date"] = pd.to_datetime(df["registration_date"]).dt.date
    for c in CATEGORICAL:
        df[c] = df[c].astype("string")
    for c in NUMERIC + REFUSAL_EXTRA + SUSPECTED_LEAK:
        df[c] = df[c].astype("float64")
    return df
