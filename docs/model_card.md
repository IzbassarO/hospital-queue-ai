# Model card — hospital-queue-ai

Three models trained on Ministry of Health open data (GovTech Camp 2026, Case 1). Full tables,
per-region and per-profile breakdowns, calibration and backtests: `reports/02_models.md`, generated
by `make train` (the report is not committed; the numbers below come from the versions trained on
2026-09-14 — wait_time `20260914-1830`, refusal_risk `20260914-1831`, load_forecast `20260914-1918`).

| model | question | output | code |
|---|---|---|---|
| A wait time | How many days will this referral wait for admission? | days | `ml/hqai_ml/models/wait_time.py` |
| B refusal risk | How likely is this referral to end in a refusal? | probability | `ml/hqai_ml/models/refusal_risk.py` |
| C load forecast | How many registrations and hospitalizations per hospital × profile / region × profile in the next 14 days? | daily counts + derived queue | `ml/hqai_ml/models/load_forecast.py` |

## 1. Purpose and intended use

- **Monitoring and prioritisation support** for health-administration staff and hospital planners:
  which referrals are likely to wait long or be refused, where daily load is heading.
- **Human in the loop, always.** Predictions flag cases for review; a person decides. The models must
  not be used to deny, delay or reorder care for an individual patient automatically, nor to rank
  hospitals for funding or sanctions.
- Explanations (top-5 factors in Russian) are there so a reviewer can check whether a flag makes
  sense — e.g. "the hospital's queue for this profile is 513" — not to prove causes (see §7).
- **Not intended** for patient-facing promises of an admission date: errors on long waits are large.

## 2. Data

- Source: the data layer built by `make ingest` (`docs/data.md`): 767 130 referrals registered
  2025-01-01 … 2025-03-31 (dataset 1), 1.51 M admission-unit refusals (dataset 3), ERSB hospital
  totals (dataset 4), daily aggregates per hospital × profile and region × profile.
- Outcomes (hospitalization / refusal dates) are observed up to the data load in May 2026.
- Personal data: none used beyond what the open data contains (no patient identifiers).

## 3. Evaluation protocol

- **Temporal split only**: train on referrals registered 2025-01-01 … 2025-02-28, test on
  2025-03-01 … 2025-03-31. No random splits.
- A, B: number of boosting rounds chosen by early stopping on the last 14 days of the train
  period (temporal), then refit on the whole train period. Fixed LightGBM defaults
  (`ml/configs/models.yaml`), no hyperparameter search. Python, NumPy and LightGBM seeds are fixed and recorded.
- C: rolling-origin backtest with canonical last-observed-day origins 2025-03-02, 03-09, 03-16, predicting first
  days 03-03, 03-10, 03-17 respectively, 14 days each; the production model is refit through 2025-03-31 and predicts
  2025-04-01 onward. This representation change does not alter the historical cutoffs or forecast rows.
- Every model is compared with naive baselines on the same test rows:
  - A: B1 global median, B2 median per profile × patient region, B3 median per hospital × profile
    (fallback B2), all from the train period.
  - B: the same three levels as refusal rates.
  - C: seasonal naive (most recent same weekday), 28-day and 7-day trailing means.
- Metrics are broken down by patient region and top-10 profiles (A, B), by series level, horizon
  bucket, region and top-20 hospitals (C).

## 4. Features and leakage review

d = registration date. All referral features are known at the start of day d.

| feature | known at | note |
|---|---|---|
| patient region, hospital, hospital region, bed profile | registration | parts of the referral code / static dictionary |
| ICD-10 chapter and 3-character code | registration | referral diagnosis |
| referral purpose, finance source, city/village | registration | referral attributes, assumed not edited later |
| weekday, day since 2025-01-01 | registration | calendar; the day index lets the model discount warm-up-biased January aggregates |
| hospital × profile queue | end of d−1 | queue on the day **before** registration |
| hospital registrations / hospitalizations, 7 and 28 days | end of d−1 | days d−7 … d−1 and d−28 … d−1 |
| hospital × profile median wait so far | end of d−1 | only referrals **hospitalized before d** (expanding) |
| hospital × profile refusal rate so far (B) | end of d−1 | only referrals **resolved before d** (expanding) |
| hospital admission-unit refusals, 28 days | end of d−1 | dataset 3, days d−28 … d−1 |
| ERSB throughput (discharges/365) and average length of stay | static, uncertain | snapshot with unknown period; may overlap the test month (mild risk) |
| **planned_lag_days — excluded** | not verifiable | see below |

**`planned_dt` is excluded.** It equals the actual admission date for 81% of hospitalized referrals,
is never empty for them, and is empty for 39% of refusals. It is evidently filled or corrected when the
hospital schedules the admission, i.e. after registration. Ablation on the test set: the planned lag
alone predicts the wait with MAE 1.4 days, and "planned date is missing" alone reaches PR-AUC 0.46 for
refusals. Using it would report leakage as accuracy. If the data owner confirms that the planned date
is fixed at registration, the product should show it directly.

Model C features use only days ≤ t (t = last known day): lags 1/2/3/7/14, trailing means 7/14/28,
the most recent same-weekday value, the queue on day t, series identifiers, horizon, and the target
date's weekday / holiday flag / day index.

## 5. Headline results (test month, March 2025)

**A — wait time** (80 436 hospitalized, non-same-day referrals; median actual wait 9 days)

| | MAE, days | median AE | WAPE | within ±7 d | Spearman |
|---|---|---|---|---|---|
| model | **10.5** | 4.0 | **45.1%** | **65.5%** | **0.73** |
| best baseline (hospital × profile median) | 11.1 | 4.0 | 47.7% | 65.1% | 0.70 |
| global median | 19.0 | 5.0 | 81.6% | 64.4% | — |

The model beats every baseline on MAE, WAPE, ±7-day share and ranking; median absolute error is tied
with the best baseline. It does not beat the hospital × profile median on MAE in 4 of 20 regions
(Aktobe, Karaganda, Kyzylorda, North Kazakhstan). The largest errors are in ophthalmology,
cardiology and neurology, where waits are long.

**B — refusal risk** (224 661 resolved referrals; refusal rate 10.9%)

| | ROC-AUC | PR-AUC | Brier | precision in top 10% | recall in top 10% |
|---|---|---|---|---|---|
| model | **0.788** | **0.384** | **0.0823** | **39.9%** | **36.5%** |
| best baseline (hospital × profile rate) | 0.761 | 0.322 | 0.0863 | 35.7% | 32.6% |
| global rate | 0.500 | 0.109 | 0.0974 | 9.4% | 8.6% |

Calibration is good: in every predicted-probability decile, mean predicted and observed rates differ
by at most 1.0 percentage point. The model beats the best baseline on ROC-AUC in all 20 regions;
ranking is weakest in Mangystau, Akmola and Aktobe (AUC 0.71–0.72).

**C — load forecast** (pooled over 3 origins × 14 days; WAPE)

| target | series | model | seasonal naive | mean 28d | mean 7d |
|---|---|---|---|---|---|
| registrations | hospital × profile, modelled (2 023) | **62.9%** | 86.4% | 102.2% | 102.2% |
| registrations | hospital × profile, fallback (4 514) | **119.7%** | 148.1% | 155.0% | 153.5% |
| registrations | region × profile (1 426) | **49.3%** | 61.7% | 86.8% | 87.2% |
| hospitalizations | hospital × profile, modelled | **68.5%** | 91.1% | 108.2% | 108.9% |
| hospitalizations | hospital × profile, fallback | **129.9%** | 151.4% | 161.4% | 160.4% |
| hospitalizations | region × profile | **56.1%** | 65.7% | 89.9% | 89.9% |

The model beats seasonal naive — the strongest baseline, because daily counts have a strong weekday
pattern — at every level and in all 6 origin × horizon cells per level. Relative errors on
hospital × profile series are high for every method because daily counts are small. Holidays remain
the main failure mode: the week of Nauryz (21–25 March) has the largest region-level errors, since
training contains only a handful of holiday days.

**Calendar fix (version `20260914-1918`).** 2025-03-10 — a transferred day off (8 March 2025 fell on
a Saturday) — was missing from the first holiday list; that day had near-zero volume and the first
model (`20260914-1823`) forecast it as a normal Monday. Adding it to `load_forecast.holidays` (a
documented public-holiday transfer, not tuning) changed pooled model WAPE: registrations —
modelled hospital series 68.3% → 62.9%, fallback 124.9% → 119.7%, region 56.5% → 49.3%;
hospitalizations — modelled 75.0% → 68.5%, fallback 135.2% → 129.9%, region 63.5% → 56.1%. Baselines
are unaffected (they do not use the calendar).

**Derived queue forecast** (last queue + Σ(forecast registrations − forecast hospitalizations)):
**worse than simply keeping the last known queue in all 18 backtest cells**, and biased upward in
14 of them because refusals also leave the queue but are not subtracted. It is written to Postgres as specified,
but should not be shown to users until refusals (or the net outflow) are forecast.

## 6. Explainability

- SHAP TreeExplainer on the LightGBM models; global importance in `reports/02_models.md`.
- Both referral models are dominated by *which hospital* and *which profile* the referral goes to,
  plus the hospital's recent history (median wait so far, queue; refusal rate so far) and the
  diagnosis.
- Per-referral explanations: `explain_referral(model, features_row)` returns the top-5 factors with
  direction, SHAP value and an effect in days / percentage points. The effects add up exactly to
  "this prediction − the average prediction". Russian sentence templates:
  `ml/configs/explain_templates.yaml`. Stored in `pred_referral.explanation` for March referrals.

## 7. Limitations and risks

- **Short history**: two months of training data and one test month; no seasonality, no
  year-over-year validation. Expect metrics to move with more data.
- **Left-censoring**: nothing before 2025-01-01, so January queues and hospitalization counts are
  under-counted. Queue features and the queue forecast are lower bounds.
- **Hindsight labels**: outcomes of train-period referrals are known up to May 2026. A model retrained
  in production on 1 March would see long February waits as still open; the evaluation therefore
  flatters long-wait accuracy somewhat.
- **Uncertain features**: ERSB snapshot period unknown; referral attributes are assumed not edited
  after registration.
- **Holidays**: learnable from only a handful of holiday days in the training period; the calendar is maintained by hand and must include transferred days off.
- **Forecast levels are not reconciled** (hospital sums ≠ region forecasts).
- **Associations, not causes**: "hospital X → +30 days" means referrals to X waited longer
  historically, not that X causes the wait or that redirecting a patient would shorten it.
- **Fairness**: the models use patient region and city/village. Differences in predictions across
  regions reflect historical access and must not be used to deprioritise patients from any region.
  Per-region error tables in the report should be reviewed before any deployment.

## 8. Reproduce

```bash
make up && make ingest     # data layer
make train ARGS="--plan"   # inspect identities, resources and checkpoint reuse without training
make train                 # models A, B, C -> artifacts/models/, reports/02_models.md
make train ARGS="--resume <run-id> --resource-profile overnight"
make predict               # -> pred_referral, pred_daily_forecast, model_registry
```

Artifacts: `artifacts/models/<model>/<version>/` (model files, `features.json`, `categories.json`,
`meta.json` with training/lineage parameters, `metrics.json`, and a deterministic SHA256
`artifact-manifest.json`); current versions in `artifacts/models/manifest.json` and
`model_registry.is_current`. The immutable scientific experiment identity and lifecycle are in
`artifacts/runs/<run-id>/run.json`; resumable unit records are under its `checkpoints/` directory.

The run record distinguishes the processed-data/input-manifest identity, normalized YAML configuration, and ML
source/Git identity, and records temporal availability rules, seeds and relevant dependency versions. Resource
limits and platform are execution metadata, allowing compatible laptop-to-overnight resume. Checksums are verified
before loading or publishing a model. This provides attributable experiment reruns; it is not a claim of
bit-for-bit numerical equality across operating systems or architectures.
