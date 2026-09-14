"""Daily aggregate tables (dense calendar for the referral aggregates)."""
import duckdb

from hqai_ml.ingest.config import IngestParams


def build_agg_daily_hospital_profile(con: duckdb.DuckDBPyConnection, p: IngestParams) -> None:
    """queue_length(d) = #referrals with registration_date <= d that are not resolved by the end of d.

    A referral is resolved on resolution_date (hospitalization or refusal date, by outcome); open
    referrals never resolve. Computed as a running sum of +1 at registration_date and -1 at
    greatest(resolution_date, registration_date) — the greatest() keeps referrals registered after
    admission (retro registrations) out of the queue — plus the carry-in from before window_start.
    """
    con.execute(
        """CREATE OR REPLACE TABLE agg_daily_hospital_profile AS
        WITH f AS (
            SELECT org_code, profile_code, registration_date, outcome, hospitalization_date, refusal_date,
                   -- DuckDB's greatest() skips NULLs: keep open referrals (no resolution) in the queue
                   CASE WHEN resolution_date IS NOT NULL
                        THEN greatest(resolution_date, registration_date) END AS leave_date
            FROM fact_referral),
        dates AS (SELECT CAST(range AS DATE) AS date FROM range($start, $end + INTERVAL 1 DAY, INTERVAL 1 DAY)),
        keys AS (SELECT DISTINCT org_code, profile_code FROM f),
        carry AS (
            SELECT org_code, profile_code,
                   -- count(*) FILTER, not count_if: count_if returns NULL when every predicate is NULL
                   count(*) FILTER (WHERE registration_date < $start)
                   - count(*) FILTER (WHERE leave_date < $start) AS n
            FROM f GROUP BY ALL),
        reg AS (SELECT org_code, profile_code, registration_date AS date, count(*) n FROM f GROUP BY ALL),
        lev AS (SELECT org_code, profile_code, leave_date AS date, count(*) n FROM f WHERE leave_date IS NOT NULL GROUP BY ALL),
        hosp AS (SELECT org_code, profile_code, hospitalization_date AS date, count(*) n FROM f
                 WHERE outcome = 'hospitalized' GROUP BY ALL),
        ref AS (SELECT org_code, profile_code, refusal_date AS date, count(*) n FROM f
                WHERE outcome = 'refused' GROUP BY ALL),
        grid AS (
            SELECT d.date, k.org_code, k.profile_code,
                   coalesce(reg.n, 0) AS registrations, coalesce(lev.n, 0) AS leaves,
                   coalesce(hosp.n, 0) AS hospitalizations, coalesce(ref.n, 0) AS refusals
            FROM dates d CROSS JOIN keys k
            LEFT JOIN reg  ON reg.org_code  = k.org_code AND reg.profile_code  = k.profile_code AND reg.date  = d.date
            LEFT JOIN lev  ON lev.org_code  = k.org_code AND lev.profile_code  = k.profile_code AND lev.date  = d.date
            LEFT JOIN hosp ON hosp.org_code = k.org_code AND hosp.profile_code = k.profile_code AND hosp.date = d.date
            LEFT JOIN ref  ON ref.org_code  = k.org_code AND ref.profile_code  = k.profile_code AND ref.date  = d.date)
        SELECT g.date, g.org_code, g.profile_code, o.region_code,
               CAST(g.registrations AS INTEGER) AS registrations,
               CAST(g.hospitalizations AS INTEGER) AS hospitalizations,
               CAST(g.refusals AS INTEGER) AS refusals,
               CAST(c.n + sum(g.registrations - g.leaves) OVER (
                   PARTITION BY g.org_code, g.profile_code ORDER BY g.date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS INTEGER) AS queue_length
        FROM grid g
        JOIN carry c ON c.org_code = g.org_code AND c.profile_code = g.profile_code
        LEFT JOIN dim_organization o ON o.org_code = g.org_code
        ORDER BY g.date, g.org_code, g.profile_code""",
        {"start": p.window_start, "end": p.window_end},
    )


def build_agg_daily_region_profile(con: duckdb.DuckDBPyConnection) -> None:
    """Roll-up of agg_daily_hospital_profile to the hospital's region (dim_organization.region_code)."""
    con.execute(
        """CREATE OR REPLACE TABLE agg_daily_region_profile AS
        SELECT date, region_code, profile_code,
               CAST(sum(registrations) AS INTEGER) AS registrations,
               CAST(sum(hospitalizations) AS INTEGER) AS hospitalizations,
               CAST(sum(refusals) AS INTEGER) AS refusals,
               CAST(sum(queue_length) AS INTEGER) AS queue_length
        FROM agg_daily_hospital_profile
        WHERE region_code IS NOT NULL
        GROUP BY ALL
        ORDER BY date, region_code, profile_code"""
    )


def build_agg_daily_admission_refusals(con: duckdb.DuckDBPyConnection) -> None:
    """Sparse: only (date, org_code) pairs with at least one refusal; rows without org_code are excluded."""
    con.execute(
        """CREATE OR REPLACE TABLE agg_daily_admission_refusals AS
        SELECT f.refuse_date AS date, f.org_code, any_value(o.region_code) AS region_code,
               CAST(count(*) AS INTEGER) AS refusals
        FROM fact_admission_refusal f JOIN dim_organization o ON o.org_code = f.org_code
        GROUP BY f.refuse_date, f.org_code
        ORDER BY date, org_code"""
    )
