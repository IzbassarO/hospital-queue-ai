#!/usr/bin/env python3
"""Descriptive baseline over the ingested data layer -> reports/01_baseline.md.

Run:  make baseline      (after make ingest)
Reads data/processed/*.parquet with DuckDB (no Postgres needed). No models.
"""
import datetime as dt
import json
import math
import re
import sys

import duckdb

from hqai_ml.ingest.config import IngestSettings
from hqai_ml.ingest.load_postgres import LOAD_ORDER

ASSUMED_ERSB_DAYS = 365  # ERSB snapshot has no period column; assumed to cover one year
MIN_THROUGHPUT_PER_DAY = 1.0
MIN_MEAN_QUEUE_FOR_GROWTH = 20
MIN_EXCESS_GROWTH_PER_WEEK = 0.05  # excess weekly growth as a share of the hospital's mean queue


# ------------------------------------------------------------------ formatting
def fmt(v, nd: int = 1) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return f"{v:,}".replace(",", " ")
    if isinstance(v, float):
        return f"{v:,.{nd}f}".replace(",", " ")
    return str(v).replace("|", "\\|")


def pct(v) -> str:
    return "—" if v is None else f"{100 * v:.1f}%"


def cut(s, n: int = 60) -> str:
    s = "—" if s is None else str(s)
    return (s[: n - 1] + "…" if len(s) > n else s).replace("|", "\\|")


_LEGAL_FORMS = [
    (r"Некоммерческое акционерное общество", "НАО"),
    (r"Акционерное общество", "АО"),
    (r"Товариществ[оа] с ограниченной ответственностью", "ТОО"),
    (r"на праве хозяйственного ведения", "на ПХВ"),
    (r"управлени[яе] здравоохранения", "УЗ"),
    (r"Республиканское государственное предприятие на праве хозяйственного ведения", "РГП на ПХВ"),
    (r"Государственное коммунальное предприятие на праве хозяйственного ведения", "ГКП на ПХВ"),
    (r"Коммунальное государственное предприятие на праве хозяйственного ведения", "КГП на ПХВ"),
    (r"Государственное коммунальное казенное предприятие", "ГККП"),
    (r"Коммунальное государственное казенное предприятие", "КГКП"),
    (r"Государственное коммунальное предприятие", "ГКП"),
    (r"Коммунальное государственное предприятия?", "КГП"),
    (r"Государственное учреждение", "ГУ"),
    (r"Учреждение", "У"),
]


def short_org(name: str | None, n: int = 70) -> str:
    """Report-only display name: standard abbreviations of legal forms."""
    s = name or "—"
    for pattern, abbr in _LEGAL_FORMS:
        s = re.sub(pattern, abbr, s, flags=re.IGNORECASE)
    return cut(s, n)


def table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---:" if i else "---" for i in range(len(header))) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out + [""]


def main() -> int:
    s = IngestSettings()
    p = s.params()
    d = s.processed_dir
    manifest = json.loads((d / "_manifest.json").read_text(encoding="utf-8"))
    con = duckdb.connect()
    for t in LOAD_ORDER:
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{d / (t + '.parquet')}')")

    def run(sql: str, params: dict | None = None):
        # DuckDB rejects unused named parameters: pass only the ones the query references
        used = {k: v for k, v in (params or {}).items() if re.search(rf"\${k}\b", sql)}
        return con.execute(sql, used)

    q = lambda sql, params=None: run(sql, params).fetchall()  # noqa: E731
    one = lambda sql, params=None: run(sql, params).fetchone()  # noqa: E731
    W = {"start": p.window_start, "end": p.window_end}

    # --- warm-up: the data starts at window_start, so referrals registered earlier and still waiting
    # are missing from the reconstructed queue. p90 of time-to-leave-the-queue bounds that effect.
    warmup_days = int(math.ceil(one(
        """SELECT quantile_cont(date_diff('day', registration_date, greatest(resolution_date, registration_date)), 0.9)
           FROM fact_referral WHERE resolution_date IS NOT NULL""")[0]))
    steady_start = p.window_start + dt.timedelta(days=warmup_days)
    L: list[str] = []

    L += ["# Baseline — planned hospitalization queues (descriptive, no models)", "",
          f"Generated {dt.datetime.now():%Y-%m-%d %H:%M} by `ml/pipelines/baseline.py` from `data/processed` "
          f"(ingest run {manifest['started_at']}).", ""]

    # ---------------------------------------------------------------- provenance
    L += ["## 0. Data and definitions", ""]
    rows = []
    for key, src in manifest["sources"].items():
        skipped = "; ".join(f"{x['file']} ({x['reason']})" for x in src.get("skipped", [])) or "none"
        staged = fmt(src["rows"]) if "rows" in src else f"not staged (only {len(src.get('region_codes', []))} region codes read)"
        rows.append([key.replace("_", " "), staged, len(src.get("files", [])), skipped])
    L += table(["source", "rows staged", "files used", "files skipped"], rows)
    L += ["All 6 parts of dataset 3 were valid in this run." if not manifest["sources"]["dataset_3"]["skipped"]
          else "**Dataset 3 is incomplete in this run — see skipped files above.**", ""]
    pg = manifest.get("postgres", {})
    L += [f"Postgres load: {'yes — row counts verified per table' if pg.get('loaded') else 'no (' + str(pg.get('reason')) + ')'}.", ""]
    L += [
        f"- **Window**: registrations {p.window_start} → {p.window_end} (daily aggregates cover the same dates).",
        "- **Wait** (`wait_days`) = calendar days from registration to hospitalization, floored at 0; hospitalized referrals only.",
        "- **Same-day registration** = hospitalized less than 24 h after registration (includes referrals registered "
        "after admission). Wait statistics are shown excluding and including them.",
        "- **Region** in wait/refusal tables = patient's region of origin (`hospitalization_code` part 1). "
        "Region in load tables = the hospital's region (`dim_organization.region_code`).",
        "- **Refusal rate** = refused referrals / all referrals.",
        f"- **Queue warm-up**: the data has no referrals registered before {p.window_start}, so the reconstructed queue "
        f"starts near zero. 90% of referrals leave the queue within **{warmup_days} days**, so queue levels are treated "
        f"as representative only from **{steady_start}**. Even then they are a lower bound (the longest waiters from "
        "before the window are missing).",
        f"- **Throughput proxy** = ERSB `discharged_total` / {ASSUMED_ERSB_DAYS} (assumption: the ERSB snapshot covers one "
        "year; the dataset has no period column).", ""]

    # ------------------------------------------------------------ wait by region
    wait_sql = """
        SELECT {key} AS k, {label} AS label,
               count(*) AS n_hosp,
               count(*) FILTER (WHERE NOT same_day_registration) AS n_excl,
               quantile_cont(wait_days, 0.5) FILTER (WHERE NOT same_day_registration) AS med_excl,
               quantile_cont(wait_days, 0.9) FILTER (WHERE NOT same_day_registration) AS p90_excl,
               quantile_cont(wait_days, 0.5) AS med_all,
               quantile_cont(wait_days, 0.9) AS p90_all,
               avg(same_day_registration::INT) AS same_day_share
        FROM fact_referral f {join}
        WHERE outcome = 'hospitalized' {where}
        GROUP BY ALL"""
    region_wait = q(wait_sql.format(key="f.region_code", label="r.region_name",
                                    join="LEFT JOIN dim_region r ON r.region_code = f.region_code", where="")
                    + " ORDER BY med_excl DESC, p90_excl DESC")
    nat = one(wait_sql.format(key="'KZ'", label="'Kazakhstan'", join="", where="").replace("GROUP BY ALL", ""))
    wait_header = ["", "name", "hospitalized", "excl. same-day: n", "median", "p90", "incl. same-day: median", "p90", "same-day share"]
    wrow = lambda r: [r[0], cut(r[1], 45), fmt(r[2]), fmt(r[3]), fmt(r[4]), fmt(r[5]), fmt(r[6]), fmt(r[7]), pct(r[8])]  # noqa: E731
    L += ["## 1. Wait days by region of origin", ""]
    L += table(["code"] + wait_header[1:], [wrow(r) for r in region_wait] + [wrow(("**all**",) + tuple(nat[1:]))])

    # ----------------------------------------------------------- wait by profile
    top_profiles = [r[0] for r in q(
        "SELECT profile_code FROM fact_referral WHERE outcome = 'hospitalized' GROUP BY 1 ORDER BY count(*) DESC LIMIT 15")]
    prof_wait = q(wait_sql.format(key="f.profile_code", label="pr.profile_name",
                                  join="LEFT JOIN dim_profile pr ON pr.profile_code = f.profile_code",
                                  where="AND f.profile_code IN (SELECT unnest($codes))")
                  + " ORDER BY med_excl DESC, p90_excl DESC", {"codes": top_profiles})
    L += ["## 2. Wait days — top-15 bed profiles by number of hospitalizations", ""]
    L += table(["profile"] + wait_header[1:], [wrow(r) for r in prof_wait])

    # ----------------------------------------------------------- refusal rates
    ref_sql = """
        SELECT {key}, {label}, count(*) n, count(*) FILTER (WHERE outcome = 'refused') refused,
               avg((outcome = 'refused')::INT) rate, count(*) FILTER (WHERE outcome = 'open') open
        FROM fact_referral f {join} {where} GROUP BY ALL"""
    ref_region = q(ref_sql.format(key="f.region_code", label="r.region_name",
                                  join="LEFT JOIN dim_region r ON r.region_code = f.region_code", where="") + " ORDER BY rate DESC")
    adm_region = dict(q("SELECT region_code, count(*) FROM fact_admission_refusal GROUP BY 1"))
    nat_ref = one("SELECT count(*), count(*) FILTER (WHERE outcome='refused'), avg((outcome='refused')::INT) FROM fact_referral")
    L += ["## 3. Refusal rate", "", "### 3a. By region of origin", "",
          "`admission-unit refusals` is dataset 3 (all refusals at hospital admission units, by hospital region) — "
          "a separate, much larger flow shown for context, not part of the rate.", ""]
    L += table(["code", "region", "referrals", "refused", "refusal rate", "open", "admission-unit refusals (ds3)"],
               [[r[0], cut(r[1], 40), fmt(r[2]), fmt(r[3]), pct(r[4]), fmt(r[5]), fmt(adm_region.get(r[0]))] for r in ref_region]
               + [["**all**", "Kazakhstan", fmt(nat_ref[0]), fmt(nat_ref[1]), pct(nat_ref[2]), "", fmt(sum(adm_region.values()))]])
    ref_prof = q(ref_sql.format(key="f.profile_code", label="pr.profile_name",
                                join="LEFT JOIN dim_profile pr ON pr.profile_code = f.profile_code",
                                where="WHERE f.profile_code IN (SELECT unnest($codes))") + " ORDER BY rate DESC",
                 {"codes": top_profiles})
    ref_prof_high = q(ref_sql.format(key="f.profile_code", label="pr.profile_name",
                                     join="LEFT JOIN dim_profile pr ON pr.profile_code = f.profile_code", where="")
                      + " HAVING count(*) >= 1000 ORDER BY rate DESC LIMIT 10")
    rrow = lambda r: [r[0], cut(r[1], 50), fmt(r[2]), fmt(r[3]), pct(r[4]), fmt(r[5])]  # noqa: E731
    L += ["### 3b. By profile (same top-15 profiles)", ""]
    L += table(["profile", "name", "referrals", "refused", "refusal rate", "open"], [rrow(r) for r in ref_prof])
    L += ["### 3c. Highest refusal rates among all profiles with ≥ 1 000 referrals", ""]
    L += table(["profile", "name", "referrals", "refused", "refusal rate", "open"], [rrow(r) for r in ref_prof_high])

    # --------------------------------------------------------- hospital load
    run(
        """CREATE TEMP TABLE org_daily AS
           SELECT date, org_code, sum(queue_length) queue, sum(registrations) regs, sum(hospitalizations) hosp
           FROM agg_daily_hospital_profile GROUP BY ALL""")
    run(
        """CREATE TEMP TABLE org_load AS
           SELECT o.org_code, o.org_name, o.region_code, r.region_name, o.match_method, e.discharged_total,
                  e.n_matched_org_codes,
                  e.discharged_total / $days AS throughput,
                  avg(od.queue) FILTER (WHERE od.date >= $steady) AS mean_queue,
                  sum(od.hosp) AS hosp_in_window
           FROM dim_organization o
           JOIN org_daily od USING (org_code)
           LEFT JOIN ersb_snapshot e ON e.ersb_id = o.ersb_id
           LEFT JOIN dim_region r ON r.region_code = o.region_code
           GROUP BY ALL""", {"days": ASSUMED_ERSB_DAYS, "steady": steady_start})
    top_load = q("""SELECT org_code, org_name, region_name, mean_queue, throughput, mean_queue / throughput ratio,
                           discharged_total, match_method, n_matched_org_codes
                    FROM org_load WHERE throughput >= $min_tp
                    ORDER BY ratio DESC LIMIT 20""", {"min_tp": MIN_THROUGHPUT_PER_DAY})
    n_eligible, ratio_p10, ratio_p50, ratio_p90 = one(
        """SELECT count(*), quantile_cont(mean_queue / throughput, [0.1, 0.5, 0.9])[1],
                  quantile_cont(mean_queue / throughput, 0.5), quantile_cont(mean_queue / throughput, 0.9)
           FROM org_load WHERE throughput >= $min_tp""", {"min_tp": MIN_THROUGHPUT_PER_DAY})
    L += ["## 4. Top-20 hospitals by queue relative to throughput", "",
          f"`mean queue` = average daily queue_length (all profiles) from {steady_start} to {p.window_end}. "
          f"`throughput/day` = ERSB discharged_total / {ASSUMED_ERSB_DAYS}. `ratio` ≈ days of discharges waiting in the "
          f"queue. Only hospitals matched to ERSB with ≥ {MIN_THROUGHPUT_PER_DAY:g} discharge/day ({n_eligible} hospitals). "
          f"Across them the ratio is p10 {fmt(ratio_p10, 2)} · median {fmt(ratio_p50, 2)} · p90 {fmt(ratio_p90, 2)}. "
          "Very high ratios usually mean a small clinic whose ERSB volume is low for the referrals it attracts — "
          "or an ERSB period shorter than the assumed year.", ""]
    L += table(["org", "hospital", "region", "mean queue", "throughput/day", "ratio", "ERSB discharged", "match"],
               [[r[0], short_org(r[1], 60), cut(r[2], 25), fmt(r[3]), fmt(r[4]), fmt(r[5]), fmt(r[6]),
                 r[7] + (f" (ERSB row shared by {r[8]} codes)" if r[8] and r[8] > 1 else "")] for r in top_load])

    region_load = q("""SELECT region_code, region_name, sum(mean_queue) FILTER (WHERE throughput IS NOT NULL) q_matched,
                              sum(throughput) tp, sum(mean_queue) q_all
                       FROM org_load GROUP BY ALL ORDER BY q_matched / tp DESC""")
    L += ["### 4b. Queue relative to throughput by hospital region", ""]
    L += table(["code", "region", "mean queue (all hospitals)", "mean queue (ERSB-matched)", "throughput/day", "ratio"],
               [[r[0], cut(r[1], 35), fmt(r[4]), fmt(r[2]), fmt(r[3]), fmt(r[2] / r[3] if r[3] else None)] for r in region_load])

    # -------------------------------------------------------- weekly national
    weekly = q("""WITH nat AS (
                      SELECT date, sum(registrations) regs, sum(hospitalizations) hosp, sum(refusals) refs, sum(queue_length) queue
                      FROM agg_daily_region_profile GROUP BY date),
                  adm AS (SELECT refuse_date date, count(*) n FROM fact_admission_refusal GROUP BY 1)
                  SELECT CAST(date_trunc('week', nat.date) AS DATE) wk, min(nat.date), max(nat.date), count(*) AS n_days,
                         sum(regs), sum(hosp), sum(refs), avg(queue), arg_max(queue, nat.date), sum(adm.n)
                  FROM nat LEFT JOIN adm USING (date) GROUP BY 1 ORDER BY 1""")
    L += ["## 5. National weekly series", "",
          "Sums over the days of each ISO week inside the window (partial weeks marked). `queue` = mean of daily "
          f"national queue_length and its value on the last day. Weeks before {steady_start} are warm-up (*).", ""]
    L += table(["week (Mon)", "days", "registrations", "hospitalizations", "refusals", "queue mean", "queue at week end",
                "admission-unit refusals (ds3)"],
               [[f"{r[0]}{' (partial)' if r[3] < 7 else ''}{' *' if r[2] < steady_start else ''}", r[3], fmt(r[4]), fmt(r[5]),
                 fmt(r[6]), fmt(r[7], 0), fmt(r[8]), fmt(r[9])] for r in weekly])

    # ---------------------------------------------------- growing hospital queues
    run(
        """CREATE TEMP TABLE org_weekly AS
           SELECT org_code, CAST(date_trunc('week', date) AS DATE) wk, avg(queue) q
           FROM org_daily WHERE date >= $steady GROUP BY ALL
           HAVING count(*) = 7""", {"steady": steady_start})
    weeks = [r[0] for r in q("SELECT DISTINCT wk FROM org_weekly ORDER BY 1")]
    # Expected growth caused only by the missing pre-window history, under a stationarity assumption
    # (arrivals and time-in-queue before the window looked like inside it). At t days after window_start
    # the queue misses  sum over resolved referrals of max(L - t, 0) / window_days  referrals, where L is
    # the referral's time in queue. The observed queue grows by the week-to-week decrease of that amount.
    window_days = (p.window_end - p.window_start).days + 1
    run(
        """CREATE TEMP TABLE org_missing AS
           WITH wk AS (SELECT DISTINCT wk, date_diff('day', $start, wk) + 3 AS t FROM org_weekly),
           lag AS (SELECT org_code, date_diff('day', registration_date, greatest(resolution_date, registration_date)) AS L
                   FROM fact_referral WHERE resolution_date IS NOT NULL)
           SELECT l.org_code, w.wk, sum(greatest(l.L - w.t, 0)) / $window_days AS missing
           FROM lag l CROSS JOIN wk w GROUP BY ALL""", {**W, "window_days": window_days})
    nat_obs, nat_art, nat_mean = one(
        """WITH n AS (SELECT wk, sum(q) q FROM org_weekly GROUP BY wk),
                m AS (SELECT wk, sum(missing) missing FROM org_missing GROUP BY wk)
           SELECT regr_slope(n.q, epoch(n.wk) / 604800), regr_slope(-m.missing, epoch(m.wk) / 604800), avg(n.q)
           FROM n JOIN m USING (wk)""")
    growth = q("""WITH w AS (
                      SELECT org_code, wk, q, q - lag(q) OVER (PARTITION BY org_code ORDER BY wk) dq FROM org_weekly),
                  g AS (
                      SELECT org_code, avg(q) mean_q, regr_slope(q, epoch(wk) / 604800) slope,
                             count(*) FILTER (WHERE dq > 0) ups, count(dq) steps,
                             arg_min(q, wk) first_q, arg_max(q, wk) last_q
                      FROM w GROUP BY org_code),
                  a AS (SELECT org_code, regr_slope(-missing, epoch(wk) / 604800) artifact FROM org_missing GROUP BY org_code),
                  x AS (SELECT g.*, coalesce(a.artifact, 0) artifact, g.slope - coalesce(a.artifact, 0) excess
                        FROM g LEFT JOIN a USING (org_code))
                  SELECT x.org_code, o.org_name, r.region_name, x.mean_q, x.first_q, x.last_q, x.slope, x.artifact,
                         x.excess, x.excess / x.mean_q rel, x.ups, x.steps
                  FROM x JOIN dim_organization o USING (org_code) LEFT JOIN dim_region r ON r.region_code = o.region_code
                  WHERE x.mean_q >= $minq AND x.steps > 0 AND x.ups >= 0.75 * x.steps AND x.excess / x.mean_q >= $min_rel
                  ORDER BY rel DESC""", {"minq": MIN_MEAN_QUEUE_FOR_GROWTH, "min_rel": MIN_EXCESS_GROWTH_PER_WEEK})
    n_big = one("SELECT count(*) FROM (SELECT org_code FROM org_weekly GROUP BY 1 HAVING avg(q) >= $minq)",
                {"minq": MIN_MEAN_QUEUE_FOR_GROWTH})[0]
    L += ["## 6. Hospitals whose queue grows week over week", "",
          f"Full ISO weeks after warm-up: {weeks[0] if weeks else '—'} … {weeks[-1] if weeks else '—'} ({len(weeks)} weeks). "
          "Part of any growth is an artifact: referrals registered before the window are missing, and they would still "
          "be leaving the queue during the window. `expected from missing history` estimates that artifact per hospital "
          "from its own arrival rate and time-in-queue distribution, assuming the months before the window looked like "
          f"the window itself. Nationally the observed queue grows by {fmt(nat_obs, 0)}/week and the missing history alone "
          f"is expected to produce {fmt(nat_art, 0)}/week"
          + (" — **the national growth is fully explained by the artifact**." if nat_art >= nat_obs
             else f" — {pct(1 - nat_art / nat_obs)} of the national growth is not explained by it."), "",
          f"Listed: hospitals with mean queue ≥ {MIN_MEAN_QUEUE_FOR_GROWTH} ({n_big} hospitals), weekly mean queue rising "
          f"in ≥ 75% of week-to-week steps, and **excess growth** (observed − expected) ≥ "
          f"{pct(MIN_EXCESS_GROWTH_PER_WEEK)} of their mean queue per week — **{len(growth)} hospitals**.", ""]
    L += table(["org", "hospital", "region", "mean queue", "first week", "last week", "observed/week",
                "expected from missing history", "excess/week", "excess % of mean", "rising steps"],
               [[r[0], short_org(r[1], 60), cut(r[2], 25), fmt(r[3]), fmt(r[4]), fmt(r[5]), fmt(r[6]), fmt(r[7]),
                 fmt(r[8]), pct(r[9]), f"{r[10]}/{r[11]}"] for r in growth[:25]])
    if len(growth) > 25:
        L += [f"… and {len(growth) - 25} more.", ""]

    # ---------------------------------------------------------------- sanity
    checks = []

    def check(name, value, expected=None, ok=None, info=False):
        status = "INFO" if info else ("PASS" if (ok if ok is not None else value == expected) else "**FAIL**")
        checks.append([name, fmt(value) if not isinstance(value, str) else value,
                       "" if expected is None else (fmt(expected) if not isinstance(expected, str) else expected), status])

    check("min queue_length (agg_daily_hospital_profile)", one("SELECT min(queue_length) FROM agg_daily_hospital_profile")[0], ">= 0",
          ok=one("SELECT min(queue_length) FROM agg_daily_hospital_profile")[0] >= 0)
    check("min queue_length (agg_daily_region_profile)", one("SELECT min(queue_length) FROM agg_daily_region_profile")[0], ">= 0",
          ok=one("SELECT min(queue_length) FROM agg_daily_region_profile")[0] >= 0)
    n_fact, n_h, n_r, n_o, n_conf = one("""SELECT count(*), count(*) FILTER (WHERE outcome='hospitalized'),
        count(*) FILTER (WHERE outcome='refused'), count(*) FILTER (WHERE outcome='open'), count(*) FILTER (WHERE outcome_conflict)
        FROM fact_referral""")
    check("hospitalized + refused + open = fact_referral rows", n_h + n_r + n_o, n_fact)
    agg = one("SELECT sum(registrations), sum(hospitalizations), sum(refusals) FROM agg_daily_hospital_profile")
    exp = one("""SELECT count(*) FILTER (WHERE registration_date BETWEEN $start AND $end),
                        count(*) FILTER (WHERE outcome='hospitalized' AND hospitalization_date BETWEEN $start AND $end),
                        count(*) FILTER (WHERE outcome='refused' AND refusal_date BETWEEN $start AND $end)
                 FROM fact_referral""", W)
    check("sum(registrations) in agg = referrals registered in window", agg[0], exp[0])
    check("sum(hospitalizations) in agg = hospitalized referrals with hospitalization_date in window", agg[1], exp[1])
    check("sum(refusals) in agg = refused referrals with refusal_date in window", agg[2], exp[2])
    ragg = one("SELECT sum(registrations), sum(hospitalizations), sum(refusals), sum(queue_length) FROM agg_daily_region_profile")
    hagg = one("SELECT sum(registrations), sum(hospitalizations), sum(refusals), sum(queue_length) FROM agg_daily_hospital_profile")
    check("region roll-up totals = hospital totals (regs, hosp, refusals, queue)", str(tuple(ragg)), str(tuple(hagg)))
    q_end_agg = one("SELECT sum(queue_length) FROM agg_daily_hospital_profile WHERE date = $end", W)[0]
    q_end_fact = one("""SELECT count(*) FROM fact_referral WHERE registration_date <= $end
                        AND (resolution_date IS NULL OR resolution_date > $end)""", W)[0]
    check(f"queue on {p.window_end}: aggregate = direct count from fact_referral", q_end_agg, q_end_fact)
    check("referrals with outcome_conflict (both dates set; counted as hospitalized)", n_conf, info=True)
    unm_region = one("""SELECT avg((r.region_code IS NULL)::INT) FROM fact_referral f
                        LEFT JOIN dim_region r ON r.region_code = f.region_code""")[0]
    check("share of referrals with region_code missing from dim_region", pct(unm_region), "0.0%", ok=unm_region == 0)
    amb = [r[0] for r in q("SELECT region_code FROM dim_region WHERE is_ambiguous ORDER BY 1")]
    amb_share = one("SELECT avg((region_code IN (SELECT unnest($c)))::INT) FROM fact_referral", {"c": amb or ['']})[0]
    check("region codes with ambiguous vote (review ml/configs/regions.yaml)", ", ".join(amb) or "none", info=True)
    check("share of referrals whose region code is ambiguous", pct(amb_share), info=True)
    unm_prof = one("""SELECT avg((pr.profile_name IS NULL)::INT) FROM fact_referral f
                      LEFT JOIN dim_profile pr ON pr.profile_code = f.profile_code""")[0]
    check("share of referrals with profile_code without a profile name", pct(unm_prof), "0.0%", ok=unm_prof == 0)
    ersb_cov = one("""SELECT avg((ersb_id IS NOT NULL)::INT), sum(n_referrals) FILTER (WHERE ersb_id IS NOT NULL) / sum(n_referrals),
                             count(*) FILTER (WHERE match_method = 'fuzzy')
                      FROM dim_organization""")
    check("hospitals matched to ERSB (share of org codes / of referrals)", f"{pct(ersb_cov[0])} / {pct(ersb_cov[1])}", info=True)
    check("of which fuzzy matches (see reports/01_org_matching.csv)", ersb_cov[2], info=True)
    ds3 = one("""SELECT avg((org_code IS NULL)::INT), avg((region_code IS NULL)::INT),
                        count(DISTINCT org_in) FILTER (WHERE org_code IS NULL) FROM fact_admission_refusal""")
    check("dataset 3 rows without org_code (hospital not in dataset 1)", f"{pct(ds3[0])} ({ds3[2]} hospitals)", info=True)
    check("dataset 3 rows without region_code", pct(ds3[1]), "0.0%", ok=ds3[1] == 0)
    adm_tot = one("SELECT sum(refusals) FROM agg_daily_admission_refusals")[0]
    adm_exp = one("SELECT count(*) FROM fact_admission_refusal WHERE org_code IS NOT NULL")[0]
    check("sum(agg_daily_admission_refusals) = dataset 3 rows with org_code", adm_tot, adm_exp)
    if pg.get("loaded"):
        mism = [t for t in LOAD_ORDER if pg["tables"][t]["rows"] != manifest["tables"][t]["rows"]]
        check("Postgres row counts = Parquet row counts (all tables)", "mismatch: " + ", ".join(mism) if mism else "equal",
              "equal", ok=not mism)
    L += ["## 7. Sanity checks", ""]
    L += table(["check", "value", "expected", "status"], checks)

    # --------------------------------------------------------------- findings
    excl = [r for r in region_wait if r[4] is not None]
    slow, fast = excl[0], excl[-1]
    rates = sorted(ref_region, key=lambda r: r[4])
    loads = [r for r in region_load if r[3]]
    prof_slowest = prof_wait[:3]
    nat_q = [r for r in weekly if r[1] >= steady_start and r[3] == 7]  # full weeks after warm-up
    L += ["## 8. Findings", ""]
    L += [
        f"1. **Regional imbalance is large.** For patients who actually waited (not admitted the same day), the median wait "
        f"ranges from {fmt(fast[4], 0)} days ({fast[1]}) to {fmt(slow[4], 0)} days ({slow[1]}); national median "
        f"{fmt(nat[4], 0)}, p90 {fmt(nat[5], 0)} days. Refusal rates range from {pct(rates[0][4])} ({rates[0][1]}) to "
        f"{pct(rates[-1][4])} ({rates[-1][1]}). Relative to ERSB throughput, queues are heaviest in "
        f"{loads[0][1]} ({fmt(loads[0][2] / loads[0][3])} days of discharges waiting) and lightest in {loads[-1][1]} "
        f"({fmt(loads[-1][2] / loads[-1][3])}).",
        "2. **Longest waits by profile** (top-15 profiles, excluding same-day): "
        + "; ".join(f"{r[1]} — median {fmt(r[4], 0)}, p90 {fmt(r[5], 0)} days" for r in prof_slowest)
        + f". Same-day admissions are {pct(nat[8])} of all hospitalizations (mostly day hospital), so any wait metric "
        "must separate them or it will look artificially short.",
        f"3. **Growing hospital queues**: after removing the growth expected from missing pre-2025 referrals, "
        f"{len(growth)} of {n_big} hospitals with a meaningful queue (mean ≥ {MIN_MEAN_QUEUE_FOR_GROWTH}) still grow by "
        f"≥ {pct(MIN_EXCESS_GROWTH_PER_WEEK)} of their queue per week and rose in most weeks"
        + (": " + "; ".join(f"{short_org(r[1], 60)} ({r[2]}, weekly mean {fmt(r[4], 0)} → {fmt(r[5], 0)})"
                            for r in growth[:3]) if growth else "")
        + ". These are the natural first candidates for queue-growth alerts.",
        f"4. **Strongest signal for the product**: queue relative to capacity. Across {n_eligible} ERSB-matched hospitals "
        f"the median hospital has {fmt(ratio_p50, 2)} days of discharges waiting, but one in ten has more than "
        f"{fmt(ratio_p90, 2)} ({fmt(ratio_p90 / ratio_p50, 0)}× the median); by hospital region the ratio ranges "
        f"{fmt(loads[-1][2] / loads[-1][3])} → {fmt(loads[0][2] / loads[0][3])}. Ranking hospitals by this ratio "
        "(section 4) shows where queues are large relative to what the hospital actually discharges — together with wait "
        "medians by origin region and the long-wait profiles (ophthalmology, endocrinology, cardiology).",
        f"5. **Caveats**: the reconstructed national queue rises after warm-up (weekly mean "
        f"{fmt(nat_q[0][7], 0) if nat_q else '—'} → {fmt(nat_q[-1][7], 0) if nat_q else '—'}), but "
        + ("all of that rise is expected from referrals missing before 2025 — there is no evidence that the national "
           "queue actually grew in Q1 2025. " if nat_art >= nat_obs else
           f"only {pct(nat_art / nat_obs)} of that rise is expected from referrals missing before 2025. ")
        + "Absolute queue levels are lower bounds. Only 3 months of registrations exist, so no seasonality can be "
        "estimated; the drop in registrations in the last full weeks of March likely reflects the Nauryz holidays "
        "(21–23 March), not a trend. ERSB throughput uses an assumed 1-year period. "
        f"Region codes {', '.join(amb) or '—'} have an ambiguous vote (cross-region patient flows) and should be confirmed in "
        "`ml/configs/regions.yaml`.",
        ""]

    out = s.reports_dir / "01_baseline.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    failed = [c for c in checks if c[3] == "**FAIL**"]
    print(f"baseline: {out}  ({len(checks)} sanity checks, {len(failed)} failed)")
    for c in failed:
        print("  FAIL:", c[0], c[1], "expected", c[2])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
