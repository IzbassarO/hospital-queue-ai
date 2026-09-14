"""Staging: raw VARCHAR tables -> typed, cleaned `stg_*` tables with normalized names."""
import duckdb

from hqai_ml.ingest.normalize import register_name_map

# Whitespace class incl. NBSP/figure/narrow spaces and BOM (RE2 \s is ASCII only).
_WS = r"[\s\x{00A0}\x{2007}\x{202F}\x{FEFF}]+"


def create_macros(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"CREATE OR REPLACE MACRO clean(x) AS nullif(trim(regexp_replace(x, '{_WS}', ' ', 'g')), '')")


def build_name_map(con: duckdb.DuckDBPyConnection) -> int:
    """One mapping for every organization/region name column in datasets 1, 3, 4."""
    return register_name_map(
        con,
        """SELECT referring_mo FROM raw_referral UNION SELECT hospital_mo FROM raw_referral
           UNION SELECT org_in FROM raw_refusal UNION SELECT attach_org FROM raw_refusal
           UNION SELECT region_in FROM raw_refusal UNION SELECT attach_region FROM raw_refusal
           UNION SELECT medicine_organization FROM raw_ersb""",
    )


def build_stg_referral(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE OR REPLACE TABLE stg_referral AS
        SELECT
            clean(r.hospitalization_code)                         AS hospitalization_code,
            split_part(clean(r.hospitalization_code), '.', 1)     AS region_code,
            split_part(clean(r.hospitalization_code), '.', 2)     AS org_code,
            split_part(clean(r.hospitalization_code), '.', 3)     AS profile_code,
            nullif(split_part(clean(r.hospitalization_code), '.', 4), '') AS seq_no,
            mr.name                                               AS referring_mo,
            mh.name                                               AS hospital_mo,
            mh.key                                                AS hospital_key,
            upper(clean(r.icd10_ref_diag_code))                   AS icd10_code,
            clean(r.diagnosis_name)                               AS diagnosis_name,
            clean(r.bed_profile)                                  AS bed_profile,
            CAST(r.registration_dt AS TIMESTAMP)                  AS registration_dt,
            CAST(r.planned_dt AS TIMESTAMP)                       AS planned_dt_raw,
            CAST(r.polyclinic_dt AS TIMESTAMP)                    AS polyclinic_dt,
            CAST(r.hospitalization_dt AS TIMESTAMP)               AS hospitalization_dt,
            CAST(r.refusal_dt AS TIMESTAMP)                       AS refusal_dt,
            clean(r.territorial_type)                             AS territorial_type,
            clean(r.referral_purpose)                             AS referral_purpose,
            clean(r.finance_source)                               AS finance_source,
            CAST(r.sdu_load_date AS TIMESTAMP)                    AS sdu_load_date
        FROM raw_referral r
        LEFT JOIN name_map mr ON mr.raw = r.referring_mo
        LEFT JOIN name_map mh ON mh.raw = r.hospital_mo"""
    )


def build_stg_refusal(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE OR REPLACE TABLE stg_refusal AS
        SELECT
            CAST(regexp_extract(r.source_file, 'Часть\\s+(\\d+)', 1) AS SMALLINT) AS source_part,
            mri.name AS region_in, mri.key AS region_in_key,
            moi.name AS org_in,    moi.key AS org_in_key,
            clean(r.resident)    AS resident,
            clean(r.insured)     AS insured,
            clean(r.benefit_cat) AS benefit_cat,
            CAST(r.refuse_dt AS TIMESTAMP) AS refuse_dt,
            mar.name AS attach_region, mar.key AS attach_region_key,
            mao.name AS attach_org,
            upper(clean(r.icd10)) AS icd10_code,
            clean(r.icd_name)     AS icd_name,
            CAST(r.amount AS DECIMAL(14, 2)) AS amount,
            clean(r.finance_src)  AS finance_src,
            CAST(r.sdu_load_date AS TIMESTAMP) AS sdu_load_date
        FROM raw_refusal r
        LEFT JOIN name_map mri ON mri.raw = r.region_in
        LEFT JOIN name_map moi ON moi.raw = r.org_in
        LEFT JOIN name_map mar ON mar.raw = r.attach_region
        LEFT JOIN name_map mao ON mao.raw = r.attach_org"""
    )


def build_stg_ersb(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """CREATE OR REPLACE TABLE stg_ersb AS
        SELECT
            CAST(e.rn AS INTEGER) AS ersb_id,   -- row number in the source file
            m.name AS org_name, m.key AS org_key,
            CAST(e.discharged_total AS INTEGER)      AS discharged_total,
            CAST(e.discharged_children AS INTEGER)   AS discharged_children,
            CAST(e.treated_budget AS INTEGER)        AS treated_budget,
            CAST(e.treated_paid AS INTEGER)          AS treated_paid,
            CAST(e.discharged_within_day AS INTEGER) AS discharged_within_day,
            CAST(e.deaths_total AS INTEGER)          AS deaths_total,
            CAST(e.bed_days AS INTEGER)              AS bed_days,
            CAST(e.amount_to_pay AS DECIMAL(20, 2))  AS amount_to_pay,
            CAST(e.sdu_load_date AS TIMESTAMP)       AS sdu_load_date
        FROM (SELECT row_number() OVER () AS rn, * FROM raw_ersb) e
        LEFT JOIN name_map m ON m.raw = e.medicine_organization
        ORDER BY e.rn"""
    )
