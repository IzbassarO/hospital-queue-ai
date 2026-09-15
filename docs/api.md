# API — hospital-queue-ai

FastAPI service that serves the specialist's scenario — *where is the load, why, what are the alternatives,
what did a person decide* — from the Postgres tables built in steps 2–3. It never trains or scores models:
it reads facts, aggregates, predictions and the serving marts.

- Base URL: `http://localhost:8000/api/v1` (`make up`); interactive docs `http://localhost:8000/docs`,
  OpenAPI schema `/openapi.json`. Local development: `make api-dev` → port 8001 with auto-reload.
- JSON only. All endpoints are read-only **except `POST /decisions`**.
- Every object carries **codes and Russian display names** from the dictionaries (`region_code` + `region_name`,
  `org_code` + `org_name`, `profile_code` + `profile_name`).
- **Pagination** on list endpoints: `limit` (1–500, default 50), `offset` (default 0); the response is
  `{"items": [...], "total": N, "limit": L, "offset": O}`.
- **Errors**: `404 {"detail": "unknown region '00'"}` for unknown codes, `422` for invalid input,
  `503 {"detail": "serving marts are not built yet: run `make marts`"}` before the first mart build.
- **CORS**: origins `http(s)://localhost:<any port>` and `127.0.0.1:<any port>` (setting `CORS_ALLOW_ORIGIN_REGEX`).
- **Latency**: every endpoint answers in < 70 ms on the current data (worst of 5 requests over HTTP against the
  docker backend, including 500-row pages); `tests/test_api.py::test_every_endpoint_under_500_ms` guards the 500 ms budget.

Contents: [1 Serving layer](#1-serving-layer) · [2 Metrics](#2-metrics) · [3 load_index](#3-load_index) ·
[4 Recommendation rule](#4-recommendation-rule-v1) · [5 Alerts](#5-alerts) · [6 Endpoints](#6-endpoints) ·
[7 Limitations](#7-limitations)

---

## 1. Serving layer

Alembic migration `0003` creates the serving tables; `ml/pipelines/build_marts.py` (`make marts`, and the last
step of `make predict`) fills them in **one transaction** (TRUNCATE + INSERT … SELECT inside Postgres, ~3 s), so
the API never sees a half-built state and a failed build keeps the previous marts. The build refuses to run if the
inputs do not cover `as_of_date` (aggregates, forecasts with `origin_date = as_of_date`, test-period predictions).

| table | grain | filled by |
|---|---|---|
| `mart_hospital_profile_status` | hospital × profile (all 6 537 pairs with referrals) | `make marts` |
| `mart_region_profile_status` | region × profile (1 426) | `make marts` |
| `mart_area_status` | totals over all profiles: one row per region + one national row (`area_code = 'KZ'`) | `make marts` |
| `mart_build_info` | one row: `as_of_date`, `built_at`, the full `serving.yaml` used, row counts | `make marts` |
| `decision_log` | one decision of a person | `POST /decisions` — never truncated by pipelines |

Parameters live in **`ml/configs/serving.yaml`** and are copied into `mart_build_info.config` at build time; the API
reads thresholds from there, so it always uses the parameters the marts were built with. Edit the YAML → `make marts`.

Windows for `as_of_date = 2025-03-31` (the last known day):

| name | dates (inclusive) |
|---|---|
| 28-day window | 2025-03-04 … 2025-03-31 |
| trend weeks (last 4 full Monday–Sunday weeks ending on or before `as_of_date`) | 2025-03-03 … 2025-03-30 |
| test period (predictions of models A/B, `ml/configs/models.yaml`) | 2025-03-01 … 2025-03-31 |
| daily series in the hospital card | 2025-02-02 … 2025-03-31 |
| forecast | origin 2025-03-31, horizons 1–14 → 2025-04-01 … 2025-04-14 |

No foreign keys from the marts or `decision_log` to the data layer: `make ingest` truncates the dictionaries and
facts, and a foreign key would either block it or cascade into the decision log. Codes in `POST /decisions` are
validated by the API instead.

## 2. Metrics

Hospital × profile rows come from `agg_daily_hospital_profile`; region × profile rows from
`agg_daily_region_profile` (regions = the **hospital's** region, `docs/data.md` §5). Area rows sum the region ×
profile rows; their medians and shares are recomputed over the underlying referrals, not averaged.

| column | definition |
|---|---|
| `queue_now` | `queue_length` on `as_of_date`: referrals waiting at the end of the day (a lower bound, `docs/data.md` §5) |
| `registrations_28d`, `hospitalizations_28d`, `refusals_28d` | sums over the 28-day window (referral refusals of dataset 1, by event date) |
| `refusal_rate_28d` | `refusals_28d / (hospitalizations_28d + refusals_28d)` — share of referrals resolved in the window that ended in a refusal; NULL when nothing was resolved |
| `median_wait_28d`, `n_waits_28d` | median `wait_days` of `fact_referral` rows with `outcome = 'hospitalized'`, `same_day_registration = false` and `hospitalization_date` in the window; the count behind it |
| `daily_throughput_28d` | `hospitalizations_28d / 28` |
| `backlog_days` | `queue_now / daily_throughput_28d` — days to clear today's queue at the recent admission rate; **NULL when throughput < 0.5 per day** |
| `forecast_registrations_14d`, `forecast_hospitalizations_14d` | sums of `pred_daily_forecast` (`origin_date = as_of_date`, horizons 1–14; hospital level for hospitals — `forecast_method` says `model` or `region_share_fallback` — region level for regions). Hospital sums are not reconciled with region forecasts |
| `n_test_referrals`, `high_risk_share` | test-period referrals in `pred_referral` and the share with `pred_refusal_prob ≥ 0.25`; NULL when there are none |
| `queue_trend_4w` | weekly mean of `queue_length` for each of the 4 trend weeks, OLS slope over week index 0–3, divided by the mean of the 4 weekly means × 100 → **% of the mean queue per week**; NULL if the mean is 0 |
| `has_sufficient_data` | `registrations_28d ≥ 10`. Rows below are listed with `status = insufficient_data` and no `load_index` |
| `status` / `status_label` | `high` (Высокая нагрузка) if `load_index ≥ 70`, `elevated` (Повышенная) if ≥ 40, `normal` (Нормальная), `insufficient_data` (Недостаточно данных) |
| `region_rank`, `region_n_ranked`, `in_region_top` | hospital rows only: rank of `load_index` among the region's hospital × profile rows (1 = highest), the number of ranked rows, and `region_rank ≤ ceil(0.20 × region_n_ranked)` |

## 3. load_index

A single 0–100 score of *how loaded this hospital × profile (or region × profile) is relative to its peers*.
Only rows with `registrations_28d ≥ 10` get one.

```
load_index = round( 100 × Σ wᵢ·sᵢ / Σ wᵢ , 1 )      over the components sᵢ that are defined

component          weight wᵢ   score sᵢ ∈ [0, 1]
backlog_rank       0.60        mid-rank percentile of backlog within the same profile nationally
refusal_rate       0.25        min(refusal_rate_28d / 0.30, 1)
queue_trend        0.15        min(max(queue_trend_4w, 0) / 20, 1)
```

**Backlog score (rank-based).** Peers = all rows of the same `profile_code` (hospital rows nationally for the
hospital mart, regions for the region mart) with sufficient data. Each row's ranking value is
`queue_now / max(daily_throughput_28d, 0.5)` — equal to `backlog_days` where that is defined, and a lower bound on
the backlog where throughput is under 0.5/day (so those rows are ranked by their queue rather than dropped, and a
queue of 1 with almost no admissions does not rank as infinite). The score is the **mid-rank percentile**

```
backlog_score = (rank − 1 + (ties − 1) / 2) / (n − 1)       rank = 1 for the smallest value; 0.5 when n = 1
```

so the row with the longest backlog in its profile gets 1, the shortest 0, and tied rows share the middle of
their positions. Ranking within the profile compares a cardiology ward with cardiology wards, not with a day
hospital.

**Refusal and trend scores** are linear with caps: a 30% refusal rate (~3× the national 10.9% of planned referrals)
or a queue growing 20% per week already count as maximal. Shrinking queues give a trend score of 0.

**Missing components** are dropped and the weights renormalised (`refusal_score` is NULL when nothing was
resolved in the window, `trend_score` when the 4-week mean queue is 0). The three scores are returned in
`components` so the UI can show what drives the index.

Worked example (`ZIQ9` × `241`, Astana perinatal centre, pathology of pregnancy): backlog 108.2 days → percentile
0.9875 among pathology-of-pregnancy wards; refusal rate 68.6% → 1.0 (capped); trend +19.1%/week → 0.955.
`100 × (0.60·0.9875 + 0.25·1.0 + 0.15·0.955) / 1.0 = 98.6`.

Weights, caps and thresholds: `ml/configs/serving.yaml` → `load_index`, `status_thresholds`,
`min_registrations_28d`, `backlog_min_daily_throughput`. The mart SQL (`ml/hqai_ml/serving/marts.py`) was checked
against an independent pandas recomputation of every metric and score for all 6 537 + 1 426 rows (0 mismatches).

## 4. Recommendation rule (v1)

`GET /hospitals/{org}/profiles/{profile}/recommendations` — `backend/app/services/recommend.py`.

1. **Trigger**: the hospital × profile has a `load_index` in the **top 20% of its region** (`in_region_top`). Otherwise
   `eligible = false`, no alternatives, `reason` explains why.
2. **Candidates**: other hospitals in the **same region and the same profile** with `registrations_28d ≥ 10` and
   `backlog_days` lower than the current hospital's (both defined; if the current backlog is undefined, `reason`
   says so).
3. **Effect estimate** (`WaitEffectEstimator` protocol): v1 `HistoricalMedianEstimator` →
   `expected_wait = median_wait_28d`; `delta_days = expected_wait_current − expected_wait_alternative`. A candidate is
   kept when `delta_days ≥ 3`.
4. **Up to 3** alternatives, largest `delta_days` first (then shorter backlog).

Each alternative returns `expected_wait_current`, `expected_wait_alternative`, `delta_days`, `refusal_rate_current`,
`refusal_rate_alternative`, backlogs, a Russian `explanation`, `method = "historical_median"` and a stable
`recommendation_id` (`rec-v1:<method>:<as_of_date>:<org>:<profile>:<alternative org>`) to reference in
`POST /decisions`.

**Swapping the estimate.** A causal module implements the same protocol —
`estimate(current, alternative) -> WaitEstimate | None` plus a `method` name — and is passed to
`recommend(session, org, profile, estimator=...)`. Trigger, candidate filters, sorting, ids and the response schema
stay unchanged; `method` in the response tells the UI which estimate it shows.

The historical median is an **association**: hospital B's patients waited less in the last 28 days; it does not mean
redirecting a patient would shorten their wait by that much (the response carries this `disclaimer`). A person
decides (`POST /decisions`).

On the current data 652 hospital × profile rows trigger the rule and 253 of them get at least one alternative.

## 5. Alerts

`GET /alerts` lists hospital × profile rows with

- `load_index ≥ 70`, **or**
- `queue_trend_4w ≥ 5%` per week, for rows with sufficient data **and `queue_now ≥ 10`** (a percentage trend on a
  queue of 1–9 is noise; `alerts.queue_trend_min_queue_now` in `serving.yaml`),

highest `load_index` first, each with Russian `reasons`. 776 alerts on the current data.

---

## 6. Endpoints

Responses below are real responses of the running service, shortened where marked `…` (lists cut to one or two items).

### `GET /health`

Database reachability and mart freshness (`503` if the database is unreachable). `GET /health` without the prefix is
a database-free liveness probe used by the container healthcheck.

```json
{"status": "ok", "database": "ok", "marts_as_of_date": "2025-03-31", "marts_built_at": "2026-09-15T09:11:25"}
```

### `GET /overview`

National KPIs and a table of the 20 regions (sorted by name). Area KPIs: queue, 28-day volumes, refusal rate, median
wait, 14-day forecast, high-risk share, `load_index_max` over hospital × profile rows, `n_hospitals_high_load` —
hospitals with at least one profile at `load_index ≥ 70`.

```json
{
  "as_of_date": "2025-03-31",
  "built_at": "2026-09-15T09:11:25",
  "thresholds": {"load_index_high": 70.0, "load_index_elevated": 40.0, "min_registrations_28d": 10},
  "national": {
    "code": "KZ", "name": "Казахстан", "level": "national",
    "queue_now": 89545, "registrations_28d": 209243, "hospitalizations_28d": 178854, "refusals_28d": 18816,
    "refusal_rate_28d": 0.0952, "median_wait_28d": 8.0, "n_waits_28d": 70284,
    "forecast_registrations_14d": 136515.6, "forecast_hospitalizations_14d": 116641.5, "high_risk_share": 0.1088,
    "n_hospitals": 1406, "n_hospital_profiles": 6537, "n_hospital_profiles_ranked": 3217,
    "load_index_max": 98.6, "n_hospitals_high_load": 241, "n_hospital_profiles_high_load": 445
  },
  "regions": [
    {
      "code": "11", "name": "Акмолинская область", "level": "region",
      "queue_now": 2186, "registrations_28d": 8690, "hospitalizations_28d": 7718, "refusals_28d": 554,
      "refusal_rate_28d": 0.067, "median_wait_28d": 7.0, "n_waits_28d": 2424,
      "forecast_registrations_14d": 5592.8, "forecast_hospitalizations_14d": 5437.7, "high_risk_share": 0.0215,
      "n_hospitals": 55, "n_hospital_profiles": 297, "n_hospital_profiles_ranked": 157,
      "load_index_max": 79.1, "n_hospitals_high_load": 6, "n_hospital_profiles_high_load": 6
    }
  ]
}
```

### `GET /regions/{code}`

Region KPIs (same shape as an overview row) and **every profile** of the region with its region × profile status,
highest `load_index` first (not paginated: at most ~90 profiles).

```json
{
  "region": {"code": "71", "name": "г. Астана", "level": "region", "queue_now": 11940, "…": "…"},
  "profiles": [
    {
      "region_code": "71", "region_name": "г. Астана", "profile_code": "614", "profile_name": "Паллиативной помощи",
      "n_hospitals": 1, "n_hospitals_high_load": 1, "load_index_max_hospital": 94.2,
      "as_of_date": "2025-03-31", "queue_now": 1, "registrations_28d": 13, "hospitalizations_28d": 10,
      "refusals_28d": 3, "refusal_rate_28d": 0.2308, "n_waits_28d": 2, "median_wait_28d": 10.5,
      "daily_throughput_28d": 0.36, "backlog_days": null, "forecast_registrations_14d": 7.5,
      "forecast_hospitalizations_14d": 6.5, "n_test_referrals": 14, "high_risk_share": 0.1429,
      "queue_trend_4w": 20.8, "has_sufficient_data": true, "load_index": 94.2,
      "status": "high", "status_label": "Высокая нагрузка",
      "components": {"backlog_score": 1.0, "refusal_score": 0.7692, "trend_score": 1.0}
    }
  ]
}
```

### `GET /regions/{code}/hospitals?profile=&limit=&offset=`

Hospital × profile rows of the region (optionally one profile), ranked by `load_index` (rows without an index last,
then by queue). `404` for an unknown region or profile.

`GET /regions/71/hospitals?profile=241&limit=2`

```json
{
  "items": [
    {
      "region_code": "71", "region_name": "г. Астана",
      "org_code": "ZIQ9",
      "org_name": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Городской перинатальный центр\" акимата города Астаны",
      "profile_code": "241", "profile_name": "Патологии беременности",
      "as_of_date": "2025-03-31", "queue_now": 85, "registrations_28d": 98, "hospitalizations_28d": 22,
      "refusals_28d": 48, "refusal_rate_28d": 0.6857, "n_waits_28d": 22, "median_wait_28d": 19.0,
      "daily_throughput_28d": 0.79, "backlog_days": 108.2, "forecast_registrations_14d": 53.1,
      "forecast_hospitalizations_14d": 21.2, "n_test_referrals": 99, "high_risk_share": 1.0, "queue_trend_4w": 19.1,
      "has_sufficient_data": true, "load_index": 98.6, "status": "high", "status_label": "Высокая нагрузка",
      "components": {"backlog_score": 0.9875, "refusal_score": 1.0, "trend_score": 0.9548},
      "forecast_method": "model", "region_rank": 1, "region_n_ranked": 244, "in_region_top": true
    }
  ],
  "total": 4, "limit": 2, "offset": 0
}
```

### `GET /hospitals/{org}/profiles/{profile}`

Status card (same object as a hospitals-list item), dense daily **series** 2025-02-02 … 2025-03-31, the 14-day
**forecast** of registrations and hospitalizations, and the **top-5 explanation factors** per model aggregated over
the hospital × profile's test-period referrals.

- Forecast: the derived queue forecast in `pred_daily_forecast.pred_queue` is deliberately **not** returned — it
  ignores refusals and lost to "last known queue" in every backtest cell (`docs/model_card.md` §5); `note` says so.
- Factors: from `pred_referral.explanation` (top-5 SHAP factors per referral). Per feature: `mean_abs_effect` and
  `mean_effect` over all referrals of the hospital × profile (a referral where the feature is not in its top 5 adds
  0), `share_in_top5`, `most_common_value`. Units: days for `wait_time`, percentage points for `refusal_risk`.
  These describe what the models associate with this hospital's predictions, not causes.

```json
{
  "status": {"org_code": "ZIQ9", "profile_code": "241", "load_index": 98.6, "queue_now": 85, "…": "…"},
  "series": [
    {"date": "2025-02-02", "registrations": 0, "hospitalizations": 1, "refusals": 1, "queue": 56},
    {"date": "2025-02-03", "registrations": 2, "hospitalizations": 3, "refusals": 0, "queue": 55},
    "… one point per day …",
    {"date": "2025-03-31", "registrations": 0, "hospitalizations": 1, "refusals": 3, "queue": 85}
  ],
  "forecast": {
    "origin_date": "2025-03-31", "model_version": "20260914-1918", "method": "model",
    "points": [
      {"date": "2025-04-01", "horizon": 1, "registrations": 5.62, "hospitalizations": 1.88},
      {"date": "2025-04-02", "horizon": 2, "registrations": 6.43, "hospitalizations": 2.12},
      "… horizons 3–14 …"
    ],
    "note": "Прогноз числа направлений и госпитализаций на 14 дней (модель C). Производный прогноз очереди не показывается: он не учитывает отказы и в бэктесте хуже, чем последнее известное значение очереди."
  },
  "explanation_factors": {
    "n_referrals": 99,
    "wait_time": [
      {"feature": "hp_median_wait_prev", "label": "медианное ожидание в стационаре по профилю до даты направления, дней",
       "mean_abs_effect": 2.99, "mean_effect": 2.99, "unit": "дн.", "direction": "up", "share_in_top5": 1.0,
       "most_common_value": "13.0"},
      {"feature": "icd3", "label": "диагноз (МКБ-10)", "mean_abs_effect": 1.89, "mean_effect": -1.09, "unit": "дн.",
       "direction": "down", "share_in_top5": 1.0, "most_common_value": "O99"},
      "… up to 5 …"
    ],
    "refusal_risk": [
      {"feature": "org_code", "label": "стационар", "mean_abs_effect": 18.35, "mean_effect": 18.35, "unit": "п.п.",
       "direction": "up", "share_in_top5": 1.0, "most_common_value": "ZIQ9"},
      {"feature": "hp_refusal_rate_prev", "label": "доля отказов в стационаре по профилю до даты направления",
       "mean_abs_effect": 11.83, "mean_effect": 11.83, "unit": "п.п.", "direction": "up", "share_in_top5": 1.0,
       "most_common_value": "0.46111111111111114"},
      "… up to 5 …"
    ]
  }
}
```

### `GET /hospitals/{org}/profiles/{profile}/referrals?sort=risk|wait&limit=&offset=`

Test-period referrals (2025-03-01 … 2025-03-31) with model outputs, sorted by refusal probability (`risk`, default)
or predicted wait (`wait`), descending. **No patient identifiers beyond `hospitalization_code`** (no internal
referral id, referring organisation or dates other than registration).

`GET /hospitals/ZIQ9/profiles/241/referrals?sort=risk&limit=1`

```json
{
  "items": [
    {
      "hospitalization_code": "71.ZIQ9.241.252", "registration_date": "2025-03-20",
      "icd10_code": "O80.0", "referral_purpose": "Консервативное лечение",
      "pred_wait_days": 13.6, "pred_refusal_prob": 0.5725, "is_high_risk": true,
      "explanation": {
        "wait_time": [
          {"shap": 0.2278, "text": "медианное ожидание в стационаре по профилю до даты направления, дней: 13,0 → +3 дня",
           "value": 13.0, "effect": 2.8659, "feature": "hp_median_wait_prev", "direction": "up"},
          "… top 5 …"
        ],
        "refusal_risk": [
          {"shap": 1.1506, "text": "стационар: ГКП на ПХВ \"Городской перинатальный центр\" акимата города Астаны (ZIQ9) → +19,7 п.п. к риску отказа",
           "value": "ZIQ9", "effect": 0.1975, "feature": "org_code", "direction": "up"},
          "… top 5 …"
        ]
      }
    }
  ],
  "total": 99, "limit": 1, "offset": 0
}
```

### `GET /hospitals/{org}/profiles/{profile}/recommendations`

Rule in [section 4](#4-recommendation-rule-v1).

```json
{
  "as_of_date": "2025-03-31",
  "region_code": "71", "region_name": "г. Астана",
  "org_code": "ZIQ9", "org_name": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Городской перинатальный центр\" акимата города Астаны",
  "profile_code": "241", "profile_name": "Патологии беременности",
  "method": "historical_median", "eligible": true, "reason": null,
  "current": {"load_index": 98.6, "status": "high", "region_rank": 1, "region_n_ranked": 244, "in_region_top": true,
              "backlog_days": 108.2, "median_wait_28d": 19.0, "refusal_rate_28d": 0.6857, "registrations_28d": 98},
  "rule": {"region_top_fraction": 0.2, "min_wait_delta_days": 3.0, "max_alternatives": 3, "min_registrations_28d": 10},
  "alternatives": [
    {
      "recommendation_id": "rec-v1:historical_median:2025-03-31:ZIQ9:241:ZH7B",
      "org_code": "ZH7B", "org_name": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Многопрофильная городская больница № 3\" акимата города Астана",
      "region_code": "71", "profile_code": "241",
      "expected_wait_current": 19.0, "expected_wait_alternative": 8.5, "delta_days": 10.5,
      "refusal_rate_current": 0.6857, "refusal_rate_alternative": 0.1079,
      "backlog_days_current": 108.2, "backlog_days_alternative": 12.4,
      "load_index_alternative": 57.5, "registrations_28d_alternative": 133,
      "method": "historical_median",
      "explanation": "В стационаре «Государственное коммунальное предприятие на праве хозяйственного ведения \"Многопрофильная городская больница № 3\" акимата города Астана» ожидаемое время ожидания госпитализации по профилю «Патологии беременности» — 8,5 дня против 19 дней в «Государственное коммунальное предприятие на праве хозяйственного ведения \"Городской перинатальный центр\" акимата города Астаны», то есть на 10,5 дня меньше (медиана за последние 28 дней). Очередь рассасывается за 12,4 дн. против 108,2 дн., доля отказов — 10,8% против 68,6%."
    },
    "… up to 3 …"
  ],
  "disclaimer": "Оценка основана на исторических медианах ожидания за последние 28 дней и не является причинным эффектом: перенаправление пациента не гарантирует такого сокращения ожидания. Решение принимает специалист."
}
```

Not triggered or no alternatives — `alternatives: []` with a reason, e.g.:

```json
{"eligible": true, "reason": "Срок рассасывания очереди не определён (меньше 0,5 госпитализации в день), поэтому сравнить стационары по очереди нельзя.", "alternatives": []}
```

### `POST /decisions`

The human-in-the-loop record. `action` ∈ `confirm | reject | defer`; `recommendation_id` and `comment` optional;
`actor` is free text for now (no authentication yet). Validation: region, hospital and profile must exist, the
hospital must belong to `region_code` and have referrals for the profile (`404` unknown region/profile, `422`
otherwise). Returns `201` with the stored row.

```json
{
  "region_code": "71", "org_code": "ZIQ9", "profile_code": "241",
  "recommendation_id": "rec-v1:historical_median:2025-03-31:ZIQ9:241:ZH7B",
  "action": "confirm",
  "comment": "Согласовано с заведующим отделением; направлять планово в ГБ № 3",
  "actor": "Иванова А. (УОЗ г. Астана)"
}
```

→ `201`

```json
{
  "region_code": "71", "org_code": "ZIQ9", "profile_code": "241",
  "recommendation_id": "rec-v1:historical_median:2025-03-31:ZIQ9:241:ZH7B",
  "action": "confirm",
  "comment": "Согласовано с заведующим отделением; направлять планово в ГБ № 3",
  "actor": "Иванова А. (УОЗ г. Астана)",
  "id": 5, "created_at": "2026-09-15T13:11:55.887730Z"
}
```

### `GET /decisions?org=&profile=&limit=&offset=`

Decisions, newest first, optionally filtered by hospital and/or profile.

```json
{"items": [{"region_code": "71", "org_code": "ZIQ9", "profile_code": "241", "recommendation_id": "rec-v1:historical_median:2025-03-31:ZIQ9:241:ZH7B", "action": "confirm", "comment": "Согласовано с заведующим отделением; направлять планово в ГБ № 3", "actor": "Иванова А. (УОЗ г. Астана)", "id": 5, "created_at": "2026-09-15T13:11:55.887730Z"}], "total": 1, "limit": 20, "offset": 0}
```

### `GET /alerts?region=&limit=&offset=`

Rule in [section 5](#5-alerts).

```json
{
  "items": [
    {
      "region_code": "71", "region_name": "г. Астана", "org_code": "ZIQ9",
      "org_name": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Городской перинатальный центр\" акимата города Астаны",
      "profile_code": "241", "profile_name": "Патологии беременности",
      "load_index": 98.6, "status": "high", "queue_now": 85, "backlog_days": 108.2, "queue_trend_4w": 19.1,
      "refusal_rate_28d": 0.6857,
      "reasons": [
        "Индекс нагрузки 98,6 ≥ 70: место 1 из 244 в регионе, очередь рассасывается за 108,2 дн.",
        "Очередь растёт на 19,1% в неделю за последние 4 недели (сейчас 85 чел.)"
      ]
    }
  ],
  "total": 776, "limit": 2, "offset": 0
}
```

### `GET /models`

Current versions from `model_registry` (`is_current`), with the model's own metrics (`headline`) and the naive
baselines evaluated on the same rows. For `load_forecast` the pooled backtest per target × series level, the
three baselines (seasonal naive, 28- and 7-day means) and `beats_baselines` (beats seasonal naive in every cell).

```json
[
  {
    "model_name": "wait_time", "title": "A · Время ожидания госпитализации (дни)", "version": "20260914-1830",
    "trained_at": "2026-09-14T18:30:40",
    "train_window": {"test": ["2025-03-01", "2025-03-31"], "train": ["2025-01-01", "2025-02-28"], "date_column": "registration_date", "early_stopping_holdout_days": 14},
    "population": {"test_rows": 80436, "definition": "hospitalized, same_day_registration = false", "train_rows": 203431, "test_median_wait": 9.0, "train_median_wait": 7.0},
    "headline": [{"n": 80436, "mae": 10.513465841246637, "wape": 0.45072504051036255, "model": "LightGBM", "spearman": 0.7330123059962853, "median_ae": 4.035894973005979, "within_7d": 0.6552911631607737}],
    "baselines": [
      {"n": 80436, "mae": 19.02745039534537, "wape": 0.8157298915268113, "model": "B1 global median", "spearman": null, "median_ae": 5.0, "within_7d": 0.6437664727236561},
      {"n": 80436, "mae": 11.118901984186186, "wape": 0.476680822758903, "model": "B3 median hospital × profile (fallback B2)", "spearman": 0.695816762385526, "median_ae": 4.0, "within_7d": 0.6505669103386543},
      "…"
    ],
    "beats_baselines": null
  },
  "… refusal_risk …",
  {
    "model_name": "load_forecast", "title": "C · Прогноз направлений и госпитализаций на 14 дней", "version": "20260914-1918",
    "…": "…",
    "headline": [{"target": "hospitalizations", "series_level": "hospital × profile (fallback)", "n": 189588, "method": "LightGBM (Poisson)", "wape": 1.2994941068602421, "mae": 0.266968352259107}, "…"],
    "baselines": [{"target": "hospitalizations", "series_level": "hospital × profile (fallback)", "n": 189588, "method": "seasonal naive (same weekday)", "wape": 1.5139541451641891, "mae": 0.31102706922379053}, "…"],
    "beats_baselines": true
  }
]
```

### `GET /dictionaries`

Regions (sorted by name) and all bed profiles, for dropdowns.

```json
{
  "national_code": "KZ",
  "regions": [{"code": "11", "name": "Акмолинская область"}, {"code": "15", "name": "Актюбинская область"}, "…"],
  "profiles": [{"code": "011", "name": "Общие", "is_day_hospital": false}, {"code": "021", "name": "Терапевтические", "is_day_hospital": false}, "…"]
}
```

---

## 7. Limitations

- **As-of snapshot, not live.** Everything is computed as of 2025-03-31, the end of the open-data window. Queue levels
  are lower bounds (no referrals before 2025-01-01, `docs/data.md` §5).
- **Rank-based backlog among sparse peers.** A profile served by few hospitals, most with empty queues, can put a row
  with a queue of 1–9 at a high backlog percentile (e.g. palliative care in Astana: queue 1, `load_index` 94.2);
  68 of the 445 rows at `load_index ≥ 70` have `queue_now < 10`. The UI should always show `queue_now` and
  `components` next to the index. `load_index` compares within a profile; it is not a capacity measure (no bed counts
  in the data).
- **Small numbers.** Rows need only 10 registrations in 28 days; refusal rates and medians behind them can rest on a
  handful of referrals (`n_waits_28d` is returned for that reason).
- **Associations, not causes** — recommendations and explanation factors (see §4 and `docs/model_card.md` §7).
- **No authentication**: `actor` is free text; `decision_log` is an audit trail of what people entered, not an identity
  record.
