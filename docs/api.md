# API — hospital-queue-ai

FastAPI service that serves the specialist's scenario — *where is the load, why, what are the alternatives,
what did a person decide* — from the Postgres tables built in steps 2–3. It never trains or scores models:
it reads facts, aggregates, predictions and the serving marts.

- Base URL: `http://localhost:8000/api/v1` (`make up`); interactive docs `http://localhost:8000/docs`,
  OpenAPI schema `/openapi.json`. Local development: `make api-dev` → port 8001 with auto-reload.
- JSON only (except the card export, which returns a file). All endpoints are read-only **except `POST /decisions`**
  and the admin key endpoints.
- **Authentication** (docs/security.md): every endpoint except `GET /health` needs an API key in the **`X-API-Key`**
  header. Roles: `viewer` — every `GET`; `specialist` — plus `POST /decisions`; `admin` — plus `/admin/*` (keys,
  access log). `401 {"detail": "missing API key"}` / `{"detail": "invalid or revoked API key"}` without a valid key,
  `403` when the role is too low. Keys: `make create-key ROLE=… LABEL=…`; the docker backend seeds `DEMO_API_KEY`
  from `.env` as a specialist key. Every `/api` request is written to `access_log`.
- Every object carries **codes and Russian display names** from the dictionaries (`region_code` + `region_name`,
  `org_code` + `org_name`, `profile_code` + `profile_name`).
- **Pagination** on list endpoints: `limit` (1–500, default 50), `offset` (default 0); the response is
  `{"items": [...], "total": N, "limit": L, "offset": O}`.
- **Errors**: `401` / `403` (above), `404 {"detail": "unknown region '00'"}` for unknown codes, `422` for invalid input,
  `409` for an `idempotency_key` reused with a different decision,
  `503 {"detail": "serving marts are not built yet: run `make marts`"}` before the first mart build.
- **CORS**: origins `http(s)://localhost:<any port>` and `127.0.0.1:<any port>` (setting `CORS_ALLOW_ORIGIN_REGEX`);
  the `X-API-Key` header is allowed, `Content-Disposition` is exposed.
- **Latency**: every endpoint answers in < 70 ms on the current data (worst of 5 requests over HTTP against the
  docker backend, including 500-row pages); `tests/test_api.py::test_every_endpoint_under_500_ms` guards the 500 ms budget.

## Contract maintenance

FastAPI/Pydantic OpenAPI is the canonical machine-readable HTTP transport contract; this document remains the
curated guide to semantics and examples. Every schema operation has an intentionally stable `operationId`, and
`backend/openapi.json` is its deterministic committed snapshot. The prefix-less container liveness route
`GET /health` remains intentionally excluded from OpenAPI; the public `GET /api/v1/health` operation is included.
Protected operations reference the `ApiKeyAuth` OpenAPI security scheme (`type: apiKey`, `in: header`,
`name: X-API-Key`); the public health operation has no security requirement. Credential values are never part of
the schema.

From the repository root, regenerate and check the backend snapshot with:

```bash
python tools/openapi_contract.py generate
python tools/openapi_contract.py check
```

After intentionally regenerating the snapshot, regenerate or check the type-only frontend transport artifacts:

```bash
cd frontend
npm run api:generate
npm run api:check
```

The machine-generated files live under `frontend/src/api/generated/` and must not be edited by hand. They provide
compile-time transport types only. The handwritten schemas in `frontend/src/api/schema.ts` and
`frontend/src/api/types.ts` continue to validate untrusted responses at runtime; their duplicated transport shapes
will be retired incrementally as frontend adapters migrate. `make audit` checks both generated layers, and GitHub CI
runs that same audit so stale snapshots, changed operation IDs and stale TypeScript output fail continuously.

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
| `decision_log` | one decision of a person; `alternative_org_code`, `idempotency_key` (unique when set), `api_key_label` (migration `0005`) | `POST /decisions` — never truncated by pipelines |
| `api_keys` | one API key: SHA-256 of the key, `key_prefix`, `role`, `label`, `created_at`, `revoked_at` | `make create-key`, `POST /admin/keys`, backend start (`DEMO_API_KEY`) |
| `access_log` | one `/api` request: `ts`, `key_label`, `role`, `method`, `path`, `status`, `latency_ms`, `client_ip`, `forwarded_for` | access-log middleware, after each response |

Parameters live in **`ml/configs/serving.yaml`** and are copied into `mart_build_info.config` at build time; the API
reads thresholds from there, so it always uses the parameters the marts were built with (`GET /config` returns them,
with the data-source description). Edit the YAML → `make marts`. Also copied at build time: the explanation display
rules and short labels (`ml/configs/explain_templates.yaml`) and names of 3-character ICD codes from `dim_icd`.
Model cards (title, intended use, limitations, display names) come from `ml/configs/model_cards.yaml` via the
artifact's `card.json` into `model_registry.card` (`make predict` or `make registry`).

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
| `queue_trend_raw_4w` | weekly mean of `queue_length` for each of the 4 trend weeks, OLS slope over week index 0–3, divided by the mean of the 4 weekly means × 100 → **% of the mean queue per week**; NULL if the mean is 0. Returned for transparency, not used for scoring |
| `queue_trend_4w` | **excess trend**: `queue_trend_raw_4w − national median` of `queue_trend_raw_4w` over the rows of the same mart with sufficient data (same 4 weeks; percentage points per week). Currently 2.57 %/week for hospital × profile and 3.23 %/week for region × profile rows — `GET /overview` returns the hospital one as `thresholds.queue_trend_national_median_4w`, `mart_build_info.config.derived` keeps both. Used by `load_index` and alerts; see §7 for why |
| `has_sufficient_data` | `registrations_28d ≥ 10`. Rows below are listed with `status = insufficient_data` and no `load_index` |
| `status` / `status_label` | `high` (Высокая нагрузка) if `load_index ≥ 70`, `elevated` (Повышенная) if ≥ 40, `normal` (Нормальная), `insufficient_data` (Недостаточно данных) |
| `high_load_share` | area rows (overview, region KPIs): `n_hospital_profiles_high_load / n_hospital_profiles_ranked` — share of the area's ranked hospital × profile rows at `load_index ≥ 70`; NULL when none is ranked. The overview table is sorted by it by default: unlike `load_index_max` it is not driven by a single row |
| `region_rank`, `region_n_ranked`, `in_region_top` | hospital rows only: rank of `load_index` among the region's hospital × profile rows (1 = highest), the number of ranked rows, and `region_rank ≤ ceil(0.20 × region_n_ranked)` |

## 3. load_index

A single 0–100 score of *how loaded this hospital × profile (or region × profile) is relative to its peers*.
Only rows with `registrations_28d ≥ 10` get one.

```
load_index = round( 100 × Σ wᵢ·sᵢ / Σ wᵢ , 1 )      over the components sᵢ that are defined

component          weight wᵢ   score sᵢ ∈ [0, 1]
backlog_rank       0.60        mid-rank percentile of backlog within the same profile nationally
refusal_rate       0.25        min(refusal_rate_28d / 0.30, 1)
queue_trend        0.15        min(max(queue_trend_4w, 0) / 20, 1)      queue_trend_4w = excess over the national median
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
or a queue growing 20 percentage points per week faster than the national median already count as maximal. Queues
growing no faster than the median (including shrinking ones) give a trend score of 0.

**Missing components** are dropped and the weights renormalised (`refusal_score` is NULL when nothing was
resolved in the window, `trend_score` when the 4-week mean queue is 0). The three scores are returned in
`components` so the UI can show what drives the index.

Worked example (`ZIQ9` × `241`, Astana perinatal centre, pathology of pregnancy): backlog 108.2 days → percentile
0.9875 among pathology-of-pregnancy wards; refusal rate 68.6% → 1.0 (capped); raw trend +19.1%/week, excess over the
national median 19.1 − 2.57 = +16.5 → 0.826. `100 × (0.60·0.9875 + 0.25·1.0 + 0.15·0.826) / 1.0 = 96.6`.

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

On the current data 651 hospital × profile rows trigger the rule and 251 of them get at least one alternative.

## 5. Alerts

`GET /alerts` lists hospital × profile rows with

- `load_index ≥ 70`, **or**
- excess trend `queue_trend_4w ≥ 5` percentage points per week **above the national median** (§2), for rows with
  sufficient data **and `queue_now ≥ 10`** (a percentage trend on a queue of 1–9 is noise;
  `alerts.queue_trend_min_queue_now` in `serving.yaml`),

highest `load_index` first, each with Russian `reasons` (the trend reason quotes the raw trend, the excess and the
median), `status_label` and the row's `region_rank` of `region_n_ranked`. Filters: `region`, `profile`, `status`
(`high | elevated | normal | insufficient_data`). 660 alerts on the current data: 252 by `load_index` only, 153 by both, 255 by the trend condition only.

Before the excess trend (raw trend ≥ 5%/week, raw trend in `load_index`) there were 776 alerts (216 / 229 / 331) and
445 rows at `load_index ≥ 70`. Switching removed 116 alerts and added none; 40 rows left `load_index ≥ 70` and none
entered (1 289 rows changed `load_index`, 61 changed `status`).

---

## 6. Endpoints

Responses below are real responses of the service, shortened where marked `…` (lists cut to one or two items). Every
request except `GET /health` carries `X-API-Key: <key>`; the role each endpoint needs is given as **role: …**.

### `GET /health`

**Open (no key).** Database reachability and mart freshness (`503` if the database is unreachable). `GET /health`
without the prefix is a database-free liveness probe used by the container healthcheck.

```json
{"status": "ok", "database": "ok", "marts_as_of_date": "2025-03-31", "marts_built_at": "2026-09-15T09:11:25"}
```

### `GET /me`

**role: viewer.** The calling key's label, role, Russian role name and permissions (the UI shows «роль: специалист»).

```json
{"label": "Иванова А. (УОЗ г. Астана)", "role": "specialist", "role_label": "специалист", "permissions": ["read", "decide"]}
```

### `GET /config`

**role: viewer.** The parameters the marts were built with (`ml/configs/serving.yaml` → `mart_build_info.config`):
windows, `load_index` weights and caps, status thresholds, the alert and recommendation rules, the national median
trend and the **data-source description** shown under the KPIs. The UI builds the formula tooltip and captions from
these values instead of hard-coding them.

```json
{
  "as_of_date": "2025-03-31",
  "built_at": "2026-09-15T18:06:47",
  "window_days": 28,
  "window_start": "2025-03-04",
  "trend_start": "2025-03-03",
  "trend_end": "2025-03-30",
  "test_start": "2025-03-01",
  "test_end": "2025-03-31",
  "series_start": "2025-02-02",
  "forecast_horizon": 14,
  "min_registrations_28d": 10,
  "backlog_min_daily_throughput": 0.5,
  "high_risk_threshold": 0.25,
  "queue_trend_national_median_4w": 2.57,
  "load_index": {
    "weights": {
      "backlog_rank": 0.6,
      "refusal_rate": 0.25,
      "queue_trend": 0.15
    },
    "refusal_rate_cap": 0.3,
    "queue_trend_cap_pct": 20.0
  },
  "status_thresholds": {
    "high": 70.0,
    "elevated": 40.0
  },
  "alerts": {
    "load_index_min": 70.0,
    "queue_trend_min_pct": 5.0,
    "queue_trend_min_queue_now": 10
  },
  "recommendations": {
    "region_top_fraction": 0.2,
    "min_wait_delta_days": 3.0,
    "max_alternatives": 3,
    "min_registrations_28d": 10
  },
  "data_source": {
    "publisher": "Министерство здравоохранения Республики Казахстан",
    "description": "Открытые данные МЗ РК: направления на плановую госпитализацию и отказы в приёмном покое (ИС «Бюро госпитализации»), пролеченные случаи по медицинским организациям (ЕРСБ).",
    "period": "направления, зарегистрированные с 01.01.2025 по 31.03.2025",
    "datasets": [
      "Направления на плановую госпитализацию (ИС «Бюро госпитализации»)",
      "Пациенты, ожидающие плановой госпитализации (ИС «Бюро госпитализации»)",
      "Отказы в госпитализации в приёмном покое (ИС «Бюро госпитализации»)",
      "Пролеченные случаи по медицинским организациям (ЕРСБ)"
    ],
    "caveats": [
      "Срез на дату as_of_date, не данные в реальном времени.",
      "Направлений до 01.01.2025 в данных нет, поэтому очереди — нижняя оценка."
    ]
  }
}
```

### `GET /overview`

**role: viewer.** National KPIs and a table of the 20 regions (sorted by name). Area KPIs: queue, 28-day volumes,
refusal rate, median wait, 14-day forecast, high-risk share, `load_index_max` over hospital × profile rows,
`n_hospitals_high_load` — hospitals with at least one profile at `load_index ≥ 70` — and `high_load_share` (§2).

```json
{
  "as_of_date": "2025-03-31",
  "built_at": "2026-09-15T18:06:47",
  "thresholds": {"load_index_high": 70.0, "load_index_elevated": 40.0, "min_registrations_28d": 10,
                 "queue_trend_national_median_4w": 2.57},
  "national": {"code": "KZ", "name": "Казахстан", "level": "national", "queue_now": 89545, "registrations_28d": 209243, "hospitalizations_28d": 178854, "refusals_28d": 18816, "refusal_rate_28d": 0.0952, "median_wait_28d": 8.0, "n_waits_28d": 70284, "forecast_registrations_14d": 136515.6, "forecast_hospitalizations_14d": 116641.5, "high_risk_share": 0.1088, "n_hospitals": 1406, "n_hospital_profiles": 6537, "n_hospital_profiles_ranked": 3217, "load_index_max": 96.6, "n_hospitals_high_load": 224, "n_hospital_profiles_high_load": 405, "high_load_share": 0.1259},
  "regions": [
    {"code": "11", "name": "Акмолинская область", "level": "region", "queue_now": 2158, "registrations_28d": 8653, "hospitalizations_28d": 7698, "refusals_28d": 553, "refusal_rate_28d": 0.067, "median_wait_28d": 7.0, "n_waits_28d": 2407, "forecast_registrations_14d": 5592.8, "forecast_hospitalizations_14d": 5437.7, "high_risk_share": 0.0216, "n_hospitals": 53, "n_hospital_profiles": 295, "n_hospital_profiles_ranked": 155, "load_index_max": 78.1, "n_hospitals_high_load": 5, "n_hospital_profiles_high_load": 5, "high_load_share": 0.0323}
  ]
}
```

### `GET /regions/{code}`

**role: viewer.** Region KPIs (same shape as an overview row) and **every profile** of the region with its region × profile status,
highest `load_index` first (not paginated: at most ~90 profiles).

```json
{
  "region": {"code": "71", "name": "г. Астана", "level": "region", "queue_now": 11940, "…": "…"},
  "profiles": [
    {
      "region_code": "71", "region_name": "г. Астана", "profile_code": "614", "profile_name": "Паллиативной помощи",
      "n_hospitals": 1, "n_hospitals_high_load": 1, "load_index_max_hospital": 92.4,
      "as_of_date": "2025-03-31", "queue_now": 1, "registrations_28d": 13, "hospitalizations_28d": 10,
      "refusals_28d": 3, "refusal_rate_28d": 0.2308, "n_waits_28d": 2, "median_wait_28d": 10.5,
      "daily_throughput_28d": 0.36, "backlog_days": null, "forecast_registrations_14d": 7.5,
      "forecast_hospitalizations_14d": 6.5, "n_test_referrals": 14, "high_risk_share": 0.1429,
      "queue_trend_raw_4w": 20.8, "queue_trend_4w": 17.6, "has_sufficient_data": true, "load_index": 92.4,
      "status": "high", "status_label": "Высокая нагрузка",
      "components": {"backlog_score": 1.0, "refusal_score": 0.7692, "trend_score": 0.8783}
    }
  ]
}
```

### `GET /regions/{code}/hospitals?profile=&limit=&offset=`

**role: viewer.** Hospital × profile rows of the region (optionally one profile), ranked by `load_index` (rows without an index last,
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
      "forecast_hospitalizations_14d": 21.2, "n_test_referrals": 99, "high_risk_share": 1.0,
      "queue_trend_raw_4w": 19.1, "queue_trend_4w": 16.5,
      "has_sufficient_data": true, "load_index": 96.6, "status": "high", "status_label": "Высокая нагрузка",
      "components": {"backlog_score": 0.9875, "refusal_score": 1.0, "trend_score": 0.8262},
      "forecast_method": "model", "region_rank": 1, "region_n_ranked": 245, "in_region_top": true
    }
  ],
  "total": 4, "limit": 2, "offset": 0
}
```

### `GET /hospitals/{org}/profiles/{profile}`

**role: viewer.** Status card (same object as a hospitals-list item), dense daily **series** 2025-02-02 … 2025-03-31, the 14-day
**forecast** of registrations and hospitalizations, and the **top-5 explanation factors** per model aggregated over
the hospital × profile's test-period referrals.

- Forecast: the derived queue forecast in `pred_daily_forecast.pred_queue` is deliberately **not** returned — it
  ignores refusals and lost to "last known queue" in every backtest cell (`docs/model_card.md` §5); `note` says so.
- Factors: from `pred_referral.explanation` (top-5 SHAP factors per referral). Per feature: `mean_abs_effect` and
  `mean_effect` over all referrals of the hospital × profile (a referral where the feature is not in its top 5 adds
  0), `share_in_top5`, `most_common_value` (raw) and `most_common_value_display`, `label` and a compact
  `short_label` (both from `ml/configs/explain_templates.yaml`). Units: days for `wait_time`, percentage points for
  `refusal_risk`.
- **Display-ready values** (`most_common_value_display` here, `value_display` next to each factor's raw `value` in
  referral explanations): rates as percentages with 1 decimal (`46,1%`), counts as integers (`75`), days with 1
  decimal (`13,0 дн.`), weekdays `Пн…Вс`, region / hospital / profile codes as `name (code)`, ICD chapters as
  `XV — name`, 3-character ICD codes as `code — name` where the data has a name for the 3-character code itself and
  otherwise `code (класс XV — chapter name)` (no ICD dictionary is in the open data; most codes in the data are
  4-character), free text as is, missing values `нет данных`. Russian number format (decimal comma). Formats per
  feature: `ml/configs/explain_templates.yaml` (copied to `mart_build_info.config.explain_display` by `make marts`);
  code: `backend/app/services/display.py`.
  These describe what the models associate with this hospital's predictions, not causes.

```json
{
  "status": {"org_code": "ZIQ9", "profile_code": "241", "load_index": 96.6, "queue_now": 85, "…": "…"},
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
      {"feature": "hp_median_wait_prev", "label": "медианное ожидание в стационаре по профилю до даты направления, дней", "short_label": "Медиана ожидания ранее", "mean_abs_effect": 2.99, "mean_effect": 2.99, "unit": "дн.", "direction": "up", "share_in_top5": 1.0, "most_common_value": "13.0", "most_common_value_display": "13,0 дн."},
      {"feature": "icd3", "label": "диагноз (МКБ-10)", "short_label": "Диагноз", "mean_abs_effect": 1.89, "mean_effect": -1.09, "unit": "дн.", "direction": "down", "share_in_top5": 1.0, "most_common_value": "O99", "most_common_value_display": "O99 — Другие болезни матери, классифицированные в других рубриках, но осложняющие беременность, роды и послеродовой период"},
      "… up to 5 …"
    ],
    "refusal_risk": [
      {"feature": "org_code", "label": "стационар", "short_label": "Стационар", "mean_abs_effect": 18.35, "mean_effect": 18.35, "unit": "п.п.", "direction": "up", "share_in_top5": 1.0, "most_common_value": "ZIQ9", "most_common_value_display": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Городской перинатальный центр\" акимата города Астаны (ZIQ9)"},
      {"feature": "hp_refusal_rate_prev", "label": "доля отказов в стационаре по профилю до даты направления", "short_label": "Доля отказов ранее", "mean_abs_effect": 11.83, "mean_effect": 11.83, "unit": "п.п.", "direction": "up", "share_in_top5": 1.0, "most_common_value": "0.46111111111111114", "most_common_value_display": "46,1%"},
      "… up to 5 …"
    ]
  }
}
```

### `GET /hospitals/{org}/profiles/{profile}/referrals?sort=risk|wait&limit=&offset=`

**role: viewer.** Test-period referrals (2025-03-01 … 2025-03-31) with model outputs, sorted by refusal probability (`risk`, default)
or predicted wait (`wait`), descending. **No patient identifiers beyond `hospitalization_code`** (no internal
referral id, referring organisation or dates other than registration). `diagnosis_name` is the name of `icd10_code` in
`dim_icd` (the most frequent spelling in the source systems — there is no official ICD dictionary in the open data).
Each factor carries `short_label`, the raw `effect` in model units (days for `wait_time`, probability share for
`refusal_risk`) and `effect_in_unit` with its `unit` (`дн.` / `п.п.`).

`GET /hospitals/ZIQ9/profiles/241/referrals?sort=risk&limit=1`

```json
{
  "items": [
    {
      "hospitalization_code": "71.ZIQ9.241.252",
      "registration_date": "2025-03-20",
      "icd10_code": "O80.0",
      "diagnosis_name": "Самопроизвольные роды в затылочном предлежании",
      "referral_purpose": "Консервативное лечение",
      "pred_wait_days": 13.6,
      "pred_refusal_prob": 0.5725,
      "is_high_risk": true,
      "explanation": {
        "wait_time": [
          {
            "shap": 0.2278,
            "text": "медианное ожидание в стационаре по профилю до даты направления, дней: 13,0 → +3 дня",
            "value": 13.0,
            "effect": 2.8659,
            "feature": "hp_median_wait_prev",
            "direction": "up",
            "value_display": "13,0 дн.",
            "short_label": "Медиана ожидания ранее",
            "unit": "дн.",
            "effect_in_unit": 2.87
          },
          "… top 5 …"
        ],
        "refusal_risk": [
          {
            "shap": 1.1506,
            "text": "стационар: ГКП на ПХВ \"Городской перинатальный центр\" акимата города Астаны (ZIQ9) → +19,7 п.п. к риску отказа",
            "value": "ZIQ9",
            "effect": 0.1975,
            "feature": "org_code",
            "direction": "up",
            "value_display": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Городской перинатальный центр\" акимата города Астаны (ZIQ9)",
            "short_label": "Стационар",
            "unit": "п.п.",
            "effect_in_unit": 19.75
          },
          "… top 5 …"
        ]
      }
    }
  ],
  "total": 99,
  "limit": 1,
  "offset": 0
}
```

### `GET /hospitals/{org}/profiles/{profile}/recommendations`

**role: viewer.** Rule in [section 4](#4-recommendation-rule-v1).

```json
{
  "as_of_date": "2025-03-31",
  "region_code": "71",
  "region_name": "г. Астана",
  "org_code": "ZIQ9",
  "org_name": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Городской перинатальный центр\" акимата города Астаны",
  "profile_code": "241",
  "profile_name": "Патологии беременности",
  "method": "historical_median",
  "eligible": true,
  "reason": null,
  "current": {
    "load_index": 96.6,
    "status": "high",
    "region_rank": 1,
    "region_n_ranked": 245,
    "in_region_top": true,
    "backlog_days": 108.2,
    "median_wait_28d": 19.0,
    "refusal_rate_28d": 0.6857,
    "registrations_28d": 98
  },
  "rule": {
    "region_top_fraction": 0.2,
    "min_wait_delta_days": 3.0,
    "max_alternatives": 3,
    "min_registrations_28d": 10
  },
  "alternatives": [
    {
      "recommendation_id": "rec-v1:historical_median:2025-03-31:ZIQ9:241:ZH7B",
      "org_code": "ZH7B",
      "org_name": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Многопрофильная городская больница № 3\" акимата города Астана",
      "region_code": "71",
      "profile_code": "241",
      "expected_wait_current": 19.0,
      "expected_wait_alternative": 8.5,
      "delta_days": 10.5,
      "refusal_rate_current": 0.6857,
      "refusal_rate_alternative": 0.1079,
      "backlog_days_current": 108.2,
      "backlog_days_alternative": 12.4,
      "load_index_alternative": 55.6,
      "registrations_28d_alternative": 133,
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

### `GET /hospitals/{org}/profiles/{profile}/export?format=xlsx|pdf`

**role: viewer.** The whole card as a file (`Content-Disposition: attachment; filename="hqai_card_<org>_<profile>_<as_of_date>.<ext>"`):
status and `load_index` components, KPIs, the daily series, the 14-day forecast (no queue forecast), explanation
factors, recommendations with the disclaimer, and the decision history — built from the same services as the JSON
endpoints.

| format | media type | content |
|---|---|---|
| `xlsx` (default) | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | sheets «Карточка», «Ряд по дням», «Прогноз 14 дней», «Почему», «Рекомендации», «Решения»; dates as Excel dates |
| `pdf` | `application/pdf` | A4: header, KPI table, queue chart, registrations fact + dashed forecast, forecast table, factors, recommendations, decisions; footer «Решение принимает специалист…» |

PDF needs a TrueType font with Cyrillic glyphs (`PDF_FONT_PATHS`; the backend image installs DejaVu Sans); without
one the endpoint answers `503`. `404` for an unknown hospital × profile, `422` for another format.

### `POST /decisions`

**role: specialist.** The human-in-the-loop record. `action` ∈ `confirm | reject | defer`; `recommendation_id`,
`alternative_org_code`, `comment` and `idempotency_key` optional; `actor` is the name the person types (free text —
the authenticated key is stored separately in `api_key_label`). Validation: region, hospital and profile must exist,
the hospital must belong to `region_code` and have referrals for the profile; the alternative must be another
hospital of the same region and match the last part of `recommendation_id` (it is derived from it when omitted)
(`404` unknown region/profile, `422` otherwise). Returns `201` with the stored row, including
`alternative_org_name` and `api_key_label`.

**Idempotency.** `idempotency_key` (8–128 characters `A–Z a–z 0–9 . _ : -`, unique index): a client generates one
per submission (the UI: `ui-<uuid>`) and resends it on retry. If the key is already stored with the same content,
the stored row is returned with **`200`** and nothing is written; with different content — **`409`**. Without a key
every request creates a row.

```json
{
  "region_code": "71",
  "org_code": "ZIQ9",
  "profile_code": "241",
  "recommendation_id": "rec-v1:historical_median:2025-03-31:ZIQ9:241:ZH7B",
  "alternative_org_code": "ZH7B",
  "action": "confirm",
  "comment": "Согласовано с заведующим отделением; направлять планово в ГБ № 3",
  "actor": "Иванова А. (УОЗ г. Астана)",
  "idempotency_key": "ui-5b1d9c0e-8f7a-4f5e-9d38-2a6f1b7c4e21"
}
```

→ `201` (the same request again → `200` with the same `id`)

```json
{
  "region_code": "71",
  "org_code": "ZIQ9",
  "profile_code": "241",
  "recommendation_id": "rec-v1:historical_median:2025-03-31:ZIQ9:241:ZH7B",
  "alternative_org_code": "ZH7B",
  "action": "confirm",
  "comment": "Согласовано с заведующим отделением; направлять планово в ГБ № 3",
  "actor": "Иванова А. (УОЗ г. Астана)",
  "idempotency_key": "ui-5b1d9c0e-8f7a-4f5e-9d38-2a6f1b7c4e21",
  "id": 54,
  "created_at": "2026-09-15T22:14:16.214850Z",
  "alternative_org_name": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Многопрофильная городская больница № 3\" акимата города Астана",
  "api_key_label": "Иванова А. (УОЗ г. Астана)"
}
```

Same key, different `action` → `409`

```json
{"detail": "idempotency_key 'ui-5b1d9c0e-8f7a-4f5e-9d38-2a6f1b7c4e21' was already used for a different decision (fields differ: action)"}
```

### `GET /decisions?org=&profile=&limit=&offset=`

**role: viewer.** Decisions, newest first, optionally filtered by hospital and/or profile.

```json
{"items": [{"region_code": "71", "org_code": "ZIQ9", "profile_code": "241", "recommendation_id": "rec-v1:historical_median:2025-03-31:ZIQ9:241:ZH7B", "alternative_org_code": "ZH7B", "action": "confirm", "comment": "Согласовано с заведующим отделением; направлять планово в ГБ № 3", "actor": "Иванова А. (УОЗ г. Астана)", "idempotency_key": "ui-5b1d9c0e-8f7a-4f5e-9d38-2a6f1b7c4e21", "id": 54, "created_at": "2026-09-15T22:14:16.214850Z", "alternative_org_name": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Многопрофильная городская больница № 3\" акимата города Астана", "api_key_label": "Иванова А. (УОЗ г. Астана)"}], "total": 1, "limit": 20, "offset": 0}
```

### `GET /alerts?region=&profile=&status=&limit=&offset=`

**role: viewer.** Rule in [section 5](#5-alerts). `GET /alerts?region=71&profile=241&status=high&limit=1`:

```json
{
  "items": [
    {
      "region_code": "71",
      "region_name": "г. Астана",
      "org_code": "ZIQ9",
      "org_name": "Государственное коммунальное предприятие на праве хозяйственного ведения \"Городской перинатальный центр\" акимата города Астаны",
      "profile_code": "241",
      "profile_name": "Патологии беременности",
      "load_index": 96.6,
      "status": "high",
      "status_label": "Высокая нагрузка",
      "region_rank": 1,
      "region_n_ranked": 245,
      "queue_now": 85,
      "backlog_days": 108.2,
      "queue_trend_raw_4w": 19.1,
      "queue_trend_4w": 16.5,
      "refusal_rate_28d": 0.6857,
      "reasons": [
        "Индекс нагрузки 96,6 ≥ 70: место 1 из 245 в регионе, очередь рассасывается за 108,2 дн.",
        "Очередь растёт на 19,1% в неделю за последние 4 недели — на 16,5 п.п. быстрее медианы по стране (2,6%); сейчас 85 чел."
      ]
    }
  ],
  "total": 2,
  "limit": 1,
  "offset": 0
}
```

### `GET /models`

**role: viewer.** Current versions from `model_registry` (`is_current`) with the **model card** — `title`,
`intended_use`, `limitations` (list of paragraphs) and `display_names` (Russian labels for the metric keys, baseline /
method names, series levels and targets that appear in `headline` / `baselines`) from `ml/configs/model_cards.yaml`
via the artifact's `card.json` — the model's own metrics (`headline`) and the naive baselines evaluated on the same
rows. For `load_forecast` the pooled backtest per target × series level, the
three baselines (seasonal naive, 28- and 7-day means) and `beats_baselines` (beats seasonal naive in every cell).

```json
[
  {
    "model_name": "wait_time",
    "title": "A · Время ожидания госпитализации (дни)",
    "intended_use": "Прогноз числа дней от направления до госпитализации для каждого направления тестового периода. Используется для объяснения нагрузки стационара и сравнения стационаров, а не для решений по отдельному пациенту.",
    "limitations": [
      "Два месяца обучения и один месяц проверки: сезонность и изменения год к году не учтены, метрики могут измениться при появлении новых данных.",
      "Ошибка выше всего в офтальмологии, кардиологии и неврологии, где ожидание долгое; в 4 из 20 регионов (Актюбинская, Карагандинская, Кызылординская, Северо-Казахстанская области) модель по MAE не лучше медианы по стационару и профилю.",
      "Прогноз отражает связи в исторических данных: «стационар X → +30 дней» не означает, что перенаправление пациента сократит ожидание на столько же."
    ],
    "display_names": {
      "mae": "MAE, дней",
      "wape": "WAPE",
      "spearman": "Корреляция Спирмена",
      "median_ae": "Медианная абсолютная ошибка, дней",
      "within_7d": "Ошибка не более 7 дней",
      "LightGBM": "Модель (LightGBM)",
      "B1 global median": "Медиана по стране",
      "B2 median profile × patient region": "Медиана по профилю и региону пациента",
      "B3 median hospital × profile (fallback B2)": "Медиана по стационару и профилю"
    },
    "version": "20260914-1830",
    "trained_at": "2026-09-14T18:30:40",
    "train_window": {
      "test": [
        "2025-03-01",
        "2025-03-31"
      ],
      "train": [
        "2025-01-01",
        "2025-02-28"
      ],
      "date_column": "registration_date",
      "early_stopping_holdout_days": 14
    },
    "population": {
      "test_rows": 80436,
      "definition": "hospitalized, same_day_registration = false",
      "train_rows": 203431,
      "test_median_wait": 9.0,
      "train_median_wait": 7.0
    },
    "headline": [
      {
        "n": 80436,
        "mae": 10.513465841246637,
        "wape": 0.45072504051036255,
        "model": "LightGBM",
        "spearman": 0.7330123059962853,
        "median_ae": 4.035894973005979,
        "within_7d": 0.6552911631607737
      }
    ],
    "baselines": [
      {
        "n": 80436,
        "mae": 19.02745039534537,
        "wape": 0.8157298915268113,
        "model": "B1 global median",
        "spearman": null,
        "median_ae": 5.0,
        "within_7d": 0.6437664727236561
      },
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

### `GET /model-assurance`

**role: viewer.** The current explicitly published Model Assurance snapshot. The scientific assurance identity,
raw-bundle hash, source commit, contract versions, freeze state and publication timestamp provide provenance for the
capability records. Publication is an administrative CLI boundary (`make assurance-publish BUNDLE=/absolute/path`),
not a runtime dependency on ML files. Returns `404` until a snapshot has been published.

### `GET /model-assurance/capabilities`

**role: viewer.** Candidate-independent assurance records for every capability in the current snapshot, sorted by
stable `capability_id`. Scientific/evidence status, product-consumption status, support, governance, freshness,
identities, limitations and allowed/forbidden claims remain separate. Local manifest and lineage paths are not part
of the response contract. Historical-flow pressure is `historical_flow_proxy_v1`, not physical capacity; decision
alternatives are retrospective mathematical alternatives for human review.

### `GET /model-assurance/capabilities/{capability_id}`

**role: viewer.** One assurance record from the current snapshot. Returns `404` when no current snapshot exists or
when the stable capability ID is absent. Governance fields explicitly retain human-review and non-autonomous-action
boundaries.

### `GET /dictionaries`

**role: viewer.** Regions (sorted by name) and all bed profiles, for dropdowns.

```json
{
  "national_code": "KZ",
  "regions": [{"code": "11", "name": "Акмолинская область"}, {"code": "15", "name": "Актюбинская область"}, "…"],
  "profiles": [{"code": "011", "name": "Общие", "is_day_hospital": false}, {"code": "021", "name": "Терапевтические", "is_day_hospital": false}, "…"]
}
```

### `GET /admin/keys`

**role: admin.** Every key with `id`, `key_prefix` (first characters, to recognise it), `role`, `label`, `created_at`,
`revoked_at`. Neither the key nor its hash is ever returned.

```json
[{"id": 6, "key_prefix": "hqai_UK8JdF", "role": "specialist", "label": "Иванова А. (УОЗ г. Астана)", "created_at": "2026-09-15T22:14:16.114853Z", "revoked_at": null}]
```

### `POST /admin/keys`

**role: admin.** Body `{"role": "viewer" | "specialist" | "admin", "label": "who uses it"}` → `201` with the new key in
`key` — **the only time it is shown** (only its SHA-256 is stored). Same as `make create-key ROLE=… LABEL=…`.

```json
{"id": 6, "key_prefix": "hqai_UK8JdF", "role": "specialist", "label": "Иванова А. (УОЗ г. Астана)", "created_at": "2026-09-15T22:14:16.114853Z", "revoked_at": null, "key": "hqai_UK8JdF…(the whole key, 48 characters, shown only here)"}
```

### `POST /admin/keys/{key_id}/revoke`

**role: admin.** Sets `revoked_at` (idempotent; `404` for an unknown id). The key gets `401` from the next request on.

```json
{"id": 6, "key_prefix": "hqai_UK8JdF", "role": "specialist", "label": "Иванова А. (УОЗ г. Астана)", "created_at": "2026-09-15T22:14:16.114853Z", "revoked_at": "2026-09-15T22:14:16.345671Z"}
```

### `GET /admin/access-log?key_label=&status=&limit=&offset=`

**role: admin.** `/api` requests, newest first (the middleware writes one row after each response, including `401`s
without a key). `client_ip` is the TCP peer — behind the docker nginx that is the frontend container;
`forwarded_for` is the `X-Forwarded-For` header as received and is not verified. Example from the docker stack
(`172.18.0.4` = nginx, `192.168.65.1` = the Docker Desktop host network):

```json
{
  "items": [
    {
      "id": 251,
      "ts": "2026-09-15T22:18:01.559600Z",
      "key_label": "demo (DEMO_API_KEY)",
      "role": "specialist",
      "method": "GET",
      "path": "/api/v1/decisions",
      "status": 200,
      "latency_ms": 11.82,
      "client_ip": "172.18.0.4",
      "forwarded_for": "192.168.65.1"
    },
    {
      "id": 250,
      "ts": "2026-09-15T22:18:01.413389Z",
      "key_label": "demo (DEMO_API_KEY)",
      "role": "specialist",
      "method": "GET",
      "path": "/api/v1/alerts",
      "status": 200,
      "latency_ms": 17.32,
      "client_ip": "172.18.0.4",
      "forwarded_for": "192.168.65.1"
    }
  ],
  "total": 19,
  "limit": 2,
  "offset": 0
}
```

---

## 7. Limitations

- **As-of snapshot, not live.** Everything is computed as of 2025-03-31, the end of the open-data window. Queue levels
  are lower bounds (no referrals before 2025-01-01, `docs/data.md` §5).
- **Rank-based backlog among sparse peers.** A profile served by few hospitals, most with empty queues, can put a row
  with a queue of 1–9 at a high backlog percentile (e.g. palliative care in Astana: queue 1, `load_index` 92.4);
  62 of the 405 rows at `load_index ≥ 70` have `queue_now < 10`. The UI should always show `queue_now` and
  `components` next to the index. `load_index` compares within a profile; it is not a capacity measure (no bed counts
  in the data).
- **Queue trends are inflated by the missing history.** No referrals before 2025-01-01 exist, so the reconstructed
  queue is still "filling up" in March: step 3 found that the national queue growth in February–March is fully
  explained by that artifact (`reports/02_models.md` §4 / `reports/01_baseline.md` §6). Over the trend weeks
  (2025-03-03 … 03-30) the national queue grows +3.3% per week and the median hospital × profile row with sufficient
  data +2.6% per week; 42% of those rows have a raw trend ≥ 5%/week. **Mitigation:** scoring and alerts use the
  excess trend over the national median (§2), which removes the common drift — 35% of rows are ≥ 5 points above
  the median, the trend component of `load_index` is 0 for rows growing no faster than the median, and 22 of the
  405 rows at `load_index ≥ 70` would fall below 70 without the trend component. It does not remove differences
  between profiles: long-wait profiles fill up longer after 2025-01-01, so their excess trend is still biased
  upward and some of the 255 trend-only alerts remain artifacts. The raw trend stays in `queue_trend_raw_4w`. With a
  longer history the bias disappears and the median correction becomes close to a no-op.
- **Small numbers.** Rows need only 10 registrations in 28 days; refusal rates and medians behind them can rest on a
  handful of referrals (`n_waits_28d` is returned for that reason).
- **Associations, not causes** — recommendations and explanation factors (see §4 and `docs/model_card.md` §7).
- **API keys, not user identity**: a key identifies a client, not a person; `actor` is still free text, and the
  demo key is added to proxied requests by the UI's own proxy, so everyone who can reach the demo UI acts as that
  specialist key (the key itself is not in the browser). What this protects and what a production deployment must
  add: [docs/security.md](security.md).
