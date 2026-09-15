"""Fact tables: fact_referral (dataset 1) and fact_admission_refusal (dataset 3)."""

import datetime as dt

import duckdb

from hqai_ml.ingest.config import IngestParams


def build_fact_referral(con: duckdb.DuckDBPyConnection, p: IngestParams) -> None:
    con.execute(
        """CREATE OR REPLACE TABLE fact_referral AS
        WITH b AS (
            SELECT s.*,
                   count(*) OVER (PARTITION BY s.hospitalization_code) > 1 AS is_dup_code,
                   coalesce(s.planned_dt_raw < $pmin OR s.planned_dt_raw >= $pmax_excl, false)
                       AS planned_dt_out_of_range,
                   CASE WHEN s.hospitalization_dt IS NOT NULL THEN 'hospitalized'
                        WHEN s.refusal_dt IS NOT NULL THEN 'refused'
                        ELSE 'open' END AS outcome,
                   s.hospitalization_dt IS NOT NULL AND s.refusal_dt IS NOT NULL AS outcome_conflict,
                   CAST(s.registration_dt AS DATE)    AS registration_date,
                   CAST(s.hospitalization_dt AS DATE) AS hospitalization_date,
                   CAST(s.refusal_dt AS DATE)         AS refusal_date
            FROM stg_referral s),
        c AS (
            SELECT b.*,
                   CASE WHEN b.planned_dt_out_of_range THEN NULL ELSE b.planned_dt_raw END AS planned_dt
            FROM b)
        SELECT
            row_number() OVER (ORDER BY c.hospitalization_code, c.registration_dt, c.hospitalization_dt NULLS LAST,
                                        c.refusal_dt NULLS LAST, c.referring_mo, c.icd10_code) AS referral_id,
            c.hospitalization_code, c.region_code, c.org_code, c.profile_code, c.seq_no, c.is_dup_code,
            o.region_code AS hospital_region_code,
            c.referring_mo, c.hospital_mo, c.icd10_code, c.diagnosis_name, c.bed_profile,
            c.registration_dt, c.planned_dt_raw, c.planned_dt, c.polyclinic_dt, c.hospitalization_dt, c.refusal_dt,
            c.territorial_type, c.referral_purpose, c.finance_source, c.sdu_load_date,
            c.outcome, c.outcome_conflict,
            c.registration_date,
            CAST(isodow(c.registration_date) AS SMALLINT) AS registration_weekday,
            CAST(date_trunc('week', c.planned_dt) AS DATE) AS planned_week,
            c.hospitalization_date, c.refusal_date,
            CASE c.outcome WHEN 'hospitalized' THEN c.hospitalization_date
                           WHEN 'refused' THEN c.refusal_date END AS resolution_date,
            CASE WHEN c.outcome = 'hospitalized'
                 THEN CAST(greatest(date_diff('day', c.registration_date, c.hospitalization_date), 0) AS INTEGER)
                     END AS wait_days,
            CASE WHEN c.outcome = 'refused'
                 THEN CAST(greatest(date_diff('day', c.registration_date, c.refusal_date), 0) AS INTEGER)
                     END AS wait_to_refusal_days,
            coalesce(c.hospitalization_dt < c.registration_dt + INTERVAL 1 DAY, false) AS same_day_registration,
            coalesce(c.hospitalization_dt < c.registration_dt, false) AS retro_registration,
            c.planned_dt_out_of_range,
            CAST(date_diff('day', c.registration_date, CAST(c.planned_dt AS DATE)) AS INTEGER) AS planned_lag_days
        FROM c LEFT JOIN dim_organization o ON o.org_code = c.org_code
        ORDER BY referral_id""",
        {"pmin": p.planned_dt_min, "pmax_excl": p.planned_dt_max + dt.timedelta(days=1)},
    )


def build_fact_admission_refusal(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE OR REPLACE TABLE fact_admission_refusal AS
        WITH keys AS (
            SELECT DISTINCT s.org_in_key, l.region_code
            FROM stg_refusal s LEFT JOIN region_lookup l ON l.key = s.region_in_key
            WHERE s.org_in_key IS NOT NULL),
        cand AS (
            SELECT k.org_in_key, k.region_code AS ds3_region_code, o.org_code,
                   count(*) OVER w AS n_cand,
                   sum(CASE WHEN o.region_code = k.region_code THEN 1 ELSE 0 END) OVER w AS n_same_region,
                   row_number() OVER (PARTITION BY k.org_in_key, k.region_code
                                      ORDER BY (o.region_code = k.region_code) DESC NULLS LAST,
                                               o.n_referrals DESC, o.org_code) AS rk
            FROM keys k JOIN dim_organization o ON o.org_key = k.org_in_key
            WINDOW w AS (PARTITION BY k.org_in_key, k.region_code)),
        org_match AS (
            SELECT org_in_key, ds3_region_code, org_code,
                   CASE WHEN n_cand = 1 THEN 'exact'
                        WHEN n_same_region = 1 THEN 'exact_region'
                        ELSE 'exact_ambiguous' END AS org_match_method
            FROM cand WHERE rk = 1)
        SELECT
            row_number() OVER (ORDER BY s.refuse_dt, s.source_part, s.org_in, s.icd10_code, s.attach_org, s.amount)
                AS refusal_id,
            s.source_part, s.region_in, lr.region_code, s.org_in, m.org_code, m.org_match_method,
            s.resident, s.insured, s.benefit_cat, s.refuse_dt, CAST(s.refuse_dt AS DATE) AS refuse_date,
            s.attach_region, la.region_code AS attach_region_code, s.attach_org,
            s.icd10_code, s.icd_name, s.amount, s.finance_src, s.sdu_load_date
        FROM stg_refusal s
        LEFT JOIN region_lookup lr ON lr.key = s.region_in_key
        LEFT JOIN region_lookup la ON la.key = s.attach_region_key
        LEFT JOIN org_match m ON m.org_in_key = s.org_in_key AND m.ds3_region_code IS NOT DISTINCT FROM lr.region_code
        ORDER BY refusal_id"""
    )
