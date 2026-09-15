"""Build the serving marts inside Postgres (formulas: docs/api.md).

mart_hospital_profile_status   one row per hospital × profile (every pair in agg_daily_hospital_profile)
mart_region_profile_status     one row per region × profile  (every pair in agg_daily_region_profile)
mart_area_status               totals over all profiles: one row per region + one national row ('KZ')
mart_build_info                id = 1: as_of_date, built_at, the serving config used, row counts

Everything runs as SQL in one transaction (TRUNCATE + INSERT … SELECT): a failure leaves the
previous marts intact, and the API never sees a half-built state.
"""
import datetime as dt
import json

import psycopg

from hqai_ml.serving.config import ServingConfig

MART_TABLES = ("mart_hospital_profile_status", "mart_region_profile_status", "mart_area_status")
NATIONAL_CODE = "KZ"
NATIONAL_NAME = "Казахстан"

# ----------------------------------------------------------------------------------------------
# Shared scoring SQL. Input relation `joined` must provide: series key columns, profile_code,
# queue_now, refusal_rate_28d, daily_throughput_28d, queue_trend_4w, has_sufficient_data.
# ----------------------------------------------------------------------------------------------
_SCORING = """
backlog AS (
    SELECT j.*,
           CASE WHEN j.daily_throughput_28d >= %(min_tp)s THEN j.queue_now / j.daily_throughput_28d END
               AS backlog_days,
           -- value used only for ranking: throughput floored at the minimum, i.e. a lower bound on the
           -- backlog, so low-throughput rows are ranked by their queue instead of being dropped
           j.queue_now / greatest(j.daily_throughput_28d, %(min_tp)s) AS backlog_rank_value
    FROM joined j
),
ranked AS (
    SELECT b.*,
           CASE WHEN b.has_sufficient_data THEN
               CASE WHEN count(*) OVER peers = 1 THEN 0.5
                    ELSE ((rank() OVER peers_ordered) - 1 + (count(*) OVER ties - 1) / 2.0)
                         / (count(*) OVER peers - 1) END
           END::float8 AS backlog_score,
           CASE WHEN b.has_sufficient_data AND b.refusal_rate_28d IS NOT NULL
                THEN least(b.refusal_rate_28d / %(refusal_cap)s, 1.0) END::float8 AS refusal_score,
           CASE WHEN b.has_sufficient_data AND b.queue_trend_4w IS NOT NULL
                THEN least(greatest(b.queue_trend_4w, 0) / %(trend_cap)s, 1.0) END::float8 AS trend_score
    FROM backlog b
    WINDOW peers AS (PARTITION BY b.profile_code, b.has_sufficient_data),
           peers_ordered AS (PARTITION BY b.profile_code, b.has_sufficient_data ORDER BY b.backlog_rank_value),
           ties AS (PARTITION BY b.profile_code, b.has_sufficient_data, b.backlog_rank_value)
),
scored AS (
    SELECT r.*,
           CASE WHEN r.has_sufficient_data THEN
               round((100.0 * (%(w_backlog)s * r.backlog_score
                               + coalesce(%(w_refusal)s * r.refusal_score, 0)
                               + coalesce(%(w_trend)s * r.trend_score, 0))
                      / nullif(%(w_backlog)s
                               + CASE WHEN r.refusal_score IS NOT NULL THEN %(w_refusal)s ELSE 0 END
                               + CASE WHEN r.trend_score IS NOT NULL THEN %(w_trend)s ELSE 0 END, 0))::numeric, 1)
           END::float8 AS load_index
    FROM ranked r
),
labelled AS (
    SELECT s.*,
           CASE WHEN NOT s.has_sufficient_data OR s.load_index IS NULL THEN 'insufficient_data'
                WHEN s.load_index >= %(status_high)s THEN 'high'
                WHEN s.load_index >= %(status_elevated)s THEN 'elevated'
                ELSE 'normal' END AS status
    FROM scored s
)
"""

_METRIC_COLUMNS = """
    as_of_date, queue_now, registrations_28d, hospitalizations_28d, refusals_28d, refusal_rate_28d,
    n_waits_28d, median_wait_28d, daily_throughput_28d, backlog_days,
    forecast_registrations_14d, forecast_hospitalizations_14d, n_test_referrals, high_risk_share,
    queue_trend_4w, has_sufficient_data, backlog_score, refusal_score, trend_score, load_index, status
"""

HOSPITAL_SQL = f"""
INSERT INTO mart_hospital_profile_status (
    org_code, profile_code, region_code, region_name, org_name, profile_name, forecast_method,
    region_rank, region_n_ranked, in_region_top, {_METRIC_COLUMNS})
WITH
base AS (
    SELECT org_code, profile_code,
           coalesce(sum(registrations) FILTER (WHERE date >= %(window_start)s), 0)::int AS registrations_28d,
           coalesce(sum(hospitalizations) FILTER (WHERE date >= %(window_start)s), 0)::int AS hospitalizations_28d,
           coalesce(sum(refusals) FILTER (WHERE date >= %(window_start)s), 0)::int AS refusals_28d,
           coalesce(max(queue_length) FILTER (WHERE date = %(as_of)s), 0)::int AS queue_now
    FROM agg_daily_hospital_profile
    WHERE date BETWEEN least(%(window_start)s, %(trend_start)s) AND %(as_of)s
    GROUP BY org_code, profile_code
),
weekly AS (
    SELECT org_code, profile_code, ((date - %(trend_start)s::date) / 7)::float8 AS week_idx,
           avg(queue_length)::float8 AS queue_mean
    FROM agg_daily_hospital_profile
    WHERE date BETWEEN %(trend_start)s AND %(trend_end)s
    GROUP BY 1, 2, 3
),
trend AS (
    SELECT org_code, profile_code,
           CASE WHEN count(*) = %(trend_weeks)s AND avg(queue_mean) > 0
                THEN regr_slope(queue_mean, week_idx) / avg(queue_mean) * 100 END AS queue_trend_4w
    FROM weekly GROUP BY 1, 2
),
waits AS (
    SELECT org_code, profile_code, count(*)::int AS n_waits_28d,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY wait_days) AS median_wait_28d
    FROM fact_referral
    WHERE outcome = 'hospitalized' AND NOT same_day_registration
      AND hospitalization_date BETWEEN %(window_start)s AND %(as_of)s
    GROUP BY 1, 2
),
fc AS (
    SELECT org_code, profile_code,
           sum(pred_registrations) AS forecast_registrations_14d,
           sum(pred_hospitalizations) AS forecast_hospitalizations_14d,
           min(method) AS forecast_method
    FROM pred_daily_forecast
    WHERE level = 'hospital' AND origin_date = %(as_of)s AND horizon BETWEEN 1 AND %(horizon)s
    GROUP BY 1, 2
),
risk AS (
    SELECT org_code, profile_code, count(*)::int AS n_test_referrals,
           avg((pred_refusal_prob >= %(high_risk)s)::int)::float8 AS high_risk_share
    FROM pred_referral
    WHERE registration_date BETWEEN %(test_start)s AND %(test_end)s
    GROUP BY 1, 2
),
joined AS (
    SELECT b.org_code, b.profile_code, o.region_code, r.region_name, o.org_name,
           coalesce(p.profile_name, b.profile_code) AS profile_name,
           b.queue_now, b.registrations_28d, b.hospitalizations_28d, b.refusals_28d,
           CASE WHEN b.hospitalizations_28d + b.refusals_28d > 0
                THEN b.refusals_28d::float8 / (b.hospitalizations_28d + b.refusals_28d) END AS refusal_rate_28d,
           coalesce(w.n_waits_28d, 0) AS n_waits_28d, w.median_wait_28d,
           b.hospitalizations_28d::float8 / %(window_days)s AS daily_throughput_28d,
           f.forecast_registrations_14d, f.forecast_hospitalizations_14d, f.forecast_method,
           coalesce(k.n_test_referrals, 0) AS n_test_referrals, k.high_risk_share,
           t.queue_trend_4w,
           b.registrations_28d >= %(min_reg)s AS has_sufficient_data
    FROM base b
    JOIN dim_organization o ON o.org_code = b.org_code
    JOIN dim_region r ON r.region_code = o.region_code
    LEFT JOIN dim_profile p ON p.profile_code = b.profile_code
    LEFT JOIN trend t ON t.org_code = b.org_code AND t.profile_code = b.profile_code
    LEFT JOIN waits w ON w.org_code = b.org_code AND w.profile_code = b.profile_code
    LEFT JOIN fc f ON f.org_code = b.org_code AND f.profile_code = b.profile_code
    LEFT JOIN risk k ON k.org_code = b.org_code AND k.profile_code = b.profile_code
),
{_SCORING},
regional AS (
    SELECT l.*,
           CASE WHEN l.load_index IS NOT NULL
                THEN rank() OVER (PARTITION BY l.region_code ORDER BY l.load_index DESC NULLS LAST) END AS region_rank,
           count(l.load_index) OVER (PARTITION BY l.region_code) AS region_n_ranked
    FROM labelled l
)
SELECT org_code, profile_code, region_code, region_name, org_name, profile_name, forecast_method,
       region_rank, region_n_ranked,
       coalesce(region_rank <= ceil(%(top_fraction)s * region_n_ranked), false) AS in_region_top,
       %(as_of)s::date, queue_now, registrations_28d, hospitalizations_28d, refusals_28d, refusal_rate_28d,
       n_waits_28d, median_wait_28d, daily_throughput_28d, backlog_days,
       forecast_registrations_14d, forecast_hospitalizations_14d, n_test_referrals, high_risk_share,
       queue_trend_4w, has_sufficient_data, backlog_score, refusal_score, trend_score, load_index, status
FROM regional
"""

REGION_SQL = f"""
INSERT INTO mart_region_profile_status (
    region_code, profile_code, region_name, profile_name, n_hospitals, n_hospitals_high_load,
    load_index_max_hospital, {_METRIC_COLUMNS})
WITH
base AS (
    SELECT region_code, profile_code,
           coalesce(sum(registrations) FILTER (WHERE date >= %(window_start)s), 0)::int AS registrations_28d,
           coalesce(sum(hospitalizations) FILTER (WHERE date >= %(window_start)s), 0)::int AS hospitalizations_28d,
           coalesce(sum(refusals) FILTER (WHERE date >= %(window_start)s), 0)::int AS refusals_28d,
           coalesce(max(queue_length) FILTER (WHERE date = %(as_of)s), 0)::int AS queue_now
    FROM agg_daily_region_profile
    WHERE date BETWEEN least(%(window_start)s, %(trend_start)s) AND %(as_of)s
    GROUP BY region_code, profile_code
),
weekly AS (
    SELECT region_code, profile_code, ((date - %(trend_start)s::date) / 7)::float8 AS week_idx,
           avg(queue_length)::float8 AS queue_mean
    FROM agg_daily_region_profile
    WHERE date BETWEEN %(trend_start)s AND %(trend_end)s
    GROUP BY 1, 2, 3
),
trend AS (
    SELECT region_code, profile_code,
           CASE WHEN count(*) = %(trend_weeks)s AND avg(queue_mean) > 0
                THEN regr_slope(queue_mean, week_idx) / avg(queue_mean) * 100 END AS queue_trend_4w
    FROM weekly GROUP BY 1, 2
),
waits AS (
    SELECT hospital_region_code AS region_code, profile_code, count(*)::int AS n_waits_28d,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY wait_days) AS median_wait_28d
    FROM fact_referral
    WHERE outcome = 'hospitalized' AND NOT same_day_registration
      AND hospitalization_date BETWEEN %(window_start)s AND %(as_of)s
    GROUP BY 1, 2
),
fc AS (
    SELECT region_code, profile_code,
           sum(pred_registrations) AS forecast_registrations_14d,
           sum(pred_hospitalizations) AS forecast_hospitalizations_14d
    FROM pred_daily_forecast
    WHERE level = 'region' AND origin_date = %(as_of)s AND horizon BETWEEN 1 AND %(horizon)s
    GROUP BY 1, 2
),
risk AS (
    SELECT o.region_code, pr.profile_code, count(*)::int AS n_test_referrals,
           avg((pr.pred_refusal_prob >= %(high_risk)s)::int)::float8 AS high_risk_share
    FROM pred_referral pr
    JOIN dim_organization o ON o.org_code = pr.org_code
    WHERE pr.registration_date BETWEEN %(test_start)s AND %(test_end)s
    GROUP BY 1, 2
),
hosp AS (
    SELECT region_code, profile_code, count(*)::int AS n_hospitals,
           (count(*) FILTER (WHERE load_index >= %(status_high)s))::int AS n_hospitals_high_load,
           max(load_index) AS load_index_max_hospital
    FROM mart_hospital_profile_status
    GROUP BY 1, 2
),
joined AS (
    SELECT b.region_code, b.profile_code, r.region_name,
           coalesce(p.profile_name, b.profile_code) AS profile_name,
           coalesce(h.n_hospitals, 0) AS n_hospitals,
           coalesce(h.n_hospitals_high_load, 0) AS n_hospitals_high_load,
           h.load_index_max_hospital,
           b.queue_now, b.registrations_28d, b.hospitalizations_28d, b.refusals_28d,
           CASE WHEN b.hospitalizations_28d + b.refusals_28d > 0
                THEN b.refusals_28d::float8 / (b.hospitalizations_28d + b.refusals_28d) END AS refusal_rate_28d,
           coalesce(w.n_waits_28d, 0) AS n_waits_28d, w.median_wait_28d,
           b.hospitalizations_28d::float8 / %(window_days)s AS daily_throughput_28d,
           f.forecast_registrations_14d, f.forecast_hospitalizations_14d,
           coalesce(k.n_test_referrals, 0) AS n_test_referrals, k.high_risk_share,
           t.queue_trend_4w,
           b.registrations_28d >= %(min_reg)s AS has_sufficient_data
    FROM base b
    JOIN dim_region r ON r.region_code = b.region_code
    LEFT JOIN dim_profile p ON p.profile_code = b.profile_code
    LEFT JOIN trend t ON t.region_code = b.region_code AND t.profile_code = b.profile_code
    LEFT JOIN waits w ON w.region_code = b.region_code AND w.profile_code = b.profile_code
    LEFT JOIN fc f ON f.region_code = b.region_code AND f.profile_code = b.profile_code
    LEFT JOIN risk k ON k.region_code = b.region_code AND k.profile_code = b.profile_code
    LEFT JOIN hosp h ON h.region_code = b.region_code AND h.profile_code = b.profile_code
),
{_SCORING}
SELECT region_code, profile_code, region_name, profile_name, n_hospitals, n_hospitals_high_load,
       load_index_max_hospital,
       %(as_of)s::date, queue_now, registrations_28d, hospitalizations_28d, refusals_28d, refusal_rate_28d,
       n_waits_28d, median_wait_28d, daily_throughput_28d, backlog_days,
       forecast_registrations_14d, forecast_hospitalizations_14d, n_test_referrals, high_risk_share,
       queue_trend_4w, has_sufficient_data, backlog_score, refusal_score, trend_score, load_index, status
FROM labelled
"""

AREA_SQL = """
INSERT INTO mart_area_status (
    area_code, area_level, area_name, as_of_date, queue_now, registrations_28d, hospitalizations_28d,
    refusals_28d, refusal_rate_28d, n_waits_28d, median_wait_28d, forecast_registrations_14d,
    forecast_hospitalizations_14d, high_risk_share, n_hospitals, n_hospital_profiles,
    n_hospital_profiles_ranked, load_index_max, n_hospitals_high_load, n_hospital_profiles_high_load)
WITH
region_totals AS (
    SELECT region_code, sum(queue_now) AS queue_now, sum(registrations_28d) AS registrations_28d,
           sum(hospitalizations_28d) AS hospitalizations_28d, sum(refusals_28d) AS refusals_28d,
           sum(forecast_registrations_14d) AS forecast_registrations_14d,
           sum(forecast_hospitalizations_14d) AS forecast_hospitalizations_14d
    FROM mart_region_profile_status GROUP BY region_code
),
wait_rows AS (
    SELECT hospital_region_code AS region_code, wait_days
    FROM fact_referral
    WHERE outcome = 'hospitalized' AND NOT same_day_registration
      AND hospitalization_date BETWEEN %(window_start)s AND %(as_of)s
),
risk_rows AS (
    SELECT o.region_code, (pr.pred_refusal_prob >= %(high_risk)s)::int AS high_risk
    FROM pred_referral pr JOIN dim_organization o ON o.org_code = pr.org_code
    WHERE pr.registration_date BETWEEN %(test_start)s AND %(test_end)s
),
hosp AS (
    SELECT region_code, count(DISTINCT org_code) AS n_hospitals, count(*) AS n_hospital_profiles,
           count(load_index) AS n_ranked, max(load_index) AS load_index_max,
           count(DISTINCT org_code) FILTER (WHERE load_index >= %(status_high)s) AS n_hospitals_high_load,
           count(*) FILTER (WHERE load_index >= %(status_high)s) AS n_hp_high_load
    FROM mart_hospital_profile_status GROUP BY region_code
),
areas AS (
    SELECT t.region_code AS area_code, 'region' AS area_level, r.region_name AS area_name,
           t.queue_now, t.registrations_28d, t.hospitalizations_28d, t.refusals_28d,
           t.forecast_registrations_14d, t.forecast_hospitalizations_14d,
           (SELECT count(*) FROM wait_rows w WHERE w.region_code = t.region_code) AS n_waits_28d,
           (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY w.wait_days) FROM wait_rows w
             WHERE w.region_code = t.region_code) AS median_wait_28d,
           (SELECT avg(k.high_risk)::float8 FROM risk_rows k WHERE k.region_code = t.region_code) AS high_risk_share,
           coalesce(h.n_hospitals, 0) AS n_hospitals, coalesce(h.n_hospital_profiles, 0) AS n_hospital_profiles,
           coalesce(h.n_ranked, 0) AS n_ranked, h.load_index_max,
           coalesce(h.n_hospitals_high_load, 0) AS n_hospitals_high_load,
           coalesce(h.n_hp_high_load, 0) AS n_hp_high_load
    FROM region_totals t
    JOIN dim_region r ON r.region_code = t.region_code
    LEFT JOIN hosp h ON h.region_code = t.region_code
    UNION ALL
    SELECT %(national_code)s, 'national', %(national_name)s,
           (SELECT sum(queue_now) FROM region_totals), (SELECT sum(registrations_28d) FROM region_totals),
           (SELECT sum(hospitalizations_28d) FROM region_totals), (SELECT sum(refusals_28d) FROM region_totals),
           (SELECT sum(forecast_registrations_14d) FROM region_totals),
           (SELECT sum(forecast_hospitalizations_14d) FROM region_totals),
           (SELECT count(*) FROM wait_rows),
           (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY wait_days) FROM wait_rows),
           (SELECT avg(high_risk)::float8 FROM risk_rows),
           (SELECT count(DISTINCT org_code) FROM mart_hospital_profile_status),
           (SELECT count(*) FROM mart_hospital_profile_status),
           (SELECT count(load_index) FROM mart_hospital_profile_status),
           (SELECT max(load_index) FROM mart_hospital_profile_status),
           (SELECT count(DISTINCT org_code) FROM mart_hospital_profile_status WHERE load_index >= %(status_high)s),
           (SELECT count(*) FROM mart_hospital_profile_status WHERE load_index >= %(status_high)s)
)
SELECT area_code, area_level, area_name, %(as_of)s::date, queue_now, registrations_28d, hospitalizations_28d,
       refusals_28d,
       CASE WHEN hospitalizations_28d + refusals_28d > 0
            THEN refusals_28d::float8 / (hospitalizations_28d + refusals_28d) END,
       n_waits_28d, median_wait_28d, forecast_registrations_14d, forecast_hospitalizations_14d, high_risk_share,
       n_hospitals, n_hospital_profiles, n_ranked, load_index_max, n_hospitals_high_load, n_hp_high_load
FROM areas
"""


def sql_params(cfg: ServingConfig, test_start: dt.date, test_end: dt.date) -> dict:
    li = cfg.load_index
    return {
        "as_of": cfg.as_of_date,
        "window_start": cfg.window_start,
        "window_days": cfg.window_days,
        "trend_start": cfg.trend_start,
        "trend_end": cfg.trend_end,
        "trend_weeks": cfg.trend_weeks,
        "horizon": cfg.forecast_horizon,
        "test_start": test_start,
        "test_end": test_end,
        "high_risk": cfg.high_risk_threshold,
        "min_reg": cfg.min_registrations_28d,
        "min_tp": cfg.backlog_min_daily_throughput,
        "refusal_cap": li.refusal_rate_cap,
        "trend_cap": li.queue_trend_cap_pct,
        "w_backlog": li.weights.backlog_rank,
        "w_refusal": li.weights.refusal_rate,
        "w_trend": li.weights.queue_trend,
        "status_high": cfg.status_thresholds.high,
        "status_elevated": cfg.status_thresholds.elevated,
        "top_fraction": cfg.recommendations.region_top_fraction,
        "national_code": NATIONAL_CODE,
        "national_name": NATIONAL_NAME,
    }


def check_inputs(cur: psycopg.Cursor, cfg: ServingConfig, test_start: dt.date, test_end: dt.date) -> dict:
    """Fail before touching the marts if the inputs do not cover as_of_date."""
    facts = {
        "agg_hospital_max_date": cur.execute("SELECT max(date) FROM agg_daily_hospital_profile").fetchone()[0],
        "agg_region_max_date": cur.execute("SELECT max(date) FROM agg_daily_region_profile").fetchone()[0],
        "agg_min_date": cur.execute("SELECT min(date) FROM agg_daily_hospital_profile").fetchone()[0],
        "forecast_rows_at_origin": cur.execute(
            "SELECT count(*) FROM pred_daily_forecast WHERE origin_date = %s", (cfg.as_of_date,)).fetchone()[0],
        "pred_referral_rows": cur.execute(
            "SELECT count(*) FROM pred_referral WHERE registration_date BETWEEN %s AND %s",
            (test_start, test_end)).fetchone()[0],
    }
    problems = []
    for key in ("agg_hospital_max_date", "agg_region_max_date"):
        if facts[key] is None or facts[key] < cfg.as_of_date:
            problems.append(f"{key} = {facts[key]} is before as_of_date {cfg.as_of_date} (run `make ingest`)")
    if facts["agg_min_date"] is None or facts["agg_min_date"] > min(cfg.trend_start, cfg.series_start):
        problems.append(f"aggregates start {facts['agg_min_date']}, after the trend/series window")
    if facts["forecast_rows_at_origin"] == 0:
        problems.append(f"pred_daily_forecast has no rows with origin_date = {cfg.as_of_date} (run `make predict`, "
                        "or align load_forecast.forecast_origin with serving.as_of_date)")
    if facts["pred_referral_rows"] == 0:
        problems.append("pred_referral is empty for the test period (run `make predict`)")
    if problems:
        raise RuntimeError("cannot build marts:\n  - " + "\n  - ".join(problems))
    return facts


def build(conninfo: str, cfg: ServingConfig, raw_config: dict, test_start: dt.date, test_end: dt.date,
          log=print) -> dict:
    params = sql_params(cfg, test_start, test_end)
    with psycopg.connect(conninfo) as con, con.cursor() as cur:
        inputs = check_inputs(cur, cfg, test_start, test_end)
        cur.execute(f"TRUNCATE {', '.join(MART_TABLES)}")
        for name, sql in (("mart_hospital_profile_status", HOSPITAL_SQL),
                          ("mart_region_profile_status", REGION_SQL),
                          ("mart_area_status", AREA_SQL)):
            cur.execute(sql, params)
            log(f"  {name}: {cur.rowcount:,} rows")

        counts = {t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in MART_TABLES}
        expected = {
            "mart_hospital_profile_status": cur.execute(
                "SELECT count(*) FROM (SELECT DISTINCT org_code, profile_code FROM agg_daily_hospital_profile) t").fetchone()[0],
            "mart_region_profile_status": cur.execute(
                "SELECT count(*) FROM (SELECT DISTINCT region_code, profile_code FROM agg_daily_region_profile) t").fetchone()[0],
            "mart_area_status": cur.execute("SELECT count(*) + 1 FROM dim_region").fetchone()[0],
        }
        if counts != expected:
            raise RuntimeError(f"mart row counts {counts} differ from the expected {expected}")

        config = {
            **raw_config,
            "derived": {
                "window_start": cfg.window_start.isoformat(), "trend_start": cfg.trend_start.isoformat(),
                "trend_end": cfg.trend_end.isoformat(), "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(), "national_code": NATIONAL_CODE,
            },
        }
        cur.execute("""INSERT INTO mart_build_info (id, as_of_date, built_at, config, row_counts)
                       VALUES (1, %s, %s, %s, %s)
                       ON CONFLICT (id) DO UPDATE SET as_of_date = EXCLUDED.as_of_date, built_at = EXCLUDED.built_at,
                           config = EXCLUDED.config, row_counts = EXCLUDED.row_counts""",
                    (cfg.as_of_date, dt.datetime.now().replace(microsecond=0),
                     json.dumps(config, ensure_ascii=False, default=str), json.dumps(counts)))
        for table in MART_TABLES:
            cur.execute(f"ANALYZE {table}")
        con.commit()
    return {"counts": counts, "inputs": inputs}
