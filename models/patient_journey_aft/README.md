# patient_journey_aft — probability that a referral is hospitalized within 7 / 14 / 30 days

**Question.** For a planned-hospitalization referral, as of its registration date, what is the probability that the
patient is hospitalized within 7, 14 and 30 days? Refusals and still-open referrals are censoring, not a second
outcome: `1 − p` is "not hospitalized by then", never a refusal probability.

**Model.** XGBoost accelerated-failure-time survival model (`survival:aft`, normal error distribution, scale
σ = 1.644, depth 6, learning rate 0.069, min child weight 5.0, 300 rounds early-stopped at iteration 289). The
booster predicts a time scale T̂ in days; the hospitalization probability by horizon h is Φ((ln h − ln T̂) / σ),
then a per-horizon calibrator fitted on the calibration week (7 d: Platt sigmoid; 14 d and 30 d: isotonic; picked
by Brier on the other half of that week). Candidate `xgboost_aft`, trial-008 of the patient-journey tournament,
refitted on the full eligible cohort in run `journey-full-confirmation-6b2a-final-20260917`.

**Training window.** Fold `q1_final` of the confirmation: train 2025-01-01 … 02-14 (early stopping on
02-15 … 02-21), calibrators on 02-22 … 02-28, test = referrals registered 2025-03-01 … 03-31 (226 046). Outcomes are
observed through the fixed label cutoff 2026-05-13, so every March referral has its full 30-day window. Eligible
cohort 767 084 of 767 130 referrals (45 events dated before registration and one dual-event conflict excluded;
same-day registrations modelled at a positive 0.5-day duration).

**Why this file.** The confirmation run holds two directories per finalist: `q1_fold_1` (trained on January only,
tested 15–28 February) and `q1_final` (`…--70e6db266e97c959`). `docs/project-evidence-index.md` cites C-index
0.847552 and mean Brier 0.109753 — the `q1_final` test values in `final-evidence.json` — so that model is shipped;
the fold-1 sibling stays in `artifacts/` as evidence. The tournament's decision is "retain both pending
product/serving tradeoff" (no single champion; human review required), which is why both this model and
`../patient_journey_hazard` are released: the AFT wins on C-index, calibration error, deployment-realistic Brier,
worst-region Brier and runtime; the hazard wins on principal and strict-sensitivity Brier.

## Input columns

One row per referral. Every value is as of the **start of the registration date** (aggregates up to the previous
day; outcome-derived statistics only from referrals resolved strictly before that date). Missing values are allowed
in every column; unseen category codes are treated as missing. `day_of_window` (calendar position) is deliberately
not a feature.

| Column | Type | Meaning |
|---|---|---|
| `region_code` | string code | patient's region of origin |
| `org_code` | string code | receiving hospital |
| `hospital_region_code` | string code | hospital's own region |
| `profile_code` | string code | hospitalization profile (specialty) |
| `icd_chapter` | string (I … XXII) | ICD-10 chapter of the diagnosis |
| `icd3` | string (e.g. `K80`) | ICD-10 code, first three characters |
| `referral_purpose` | string code | purpose of the referral |
| `finance_source` | string code | financing source |
| `territorial_type` | string code | city / village |
| `registration_weekday` | float, 1 … 7 | ISO weekday of registration |
| `queue_hp_prev_day` | float | hospital × profile queue length on the previous day |
| `hosp_reg_7d`, `hosp_reg_28d` | float | hospital registrations in the previous 7 / 28 days |
| `hosp_hosp_7d`, `hosp_hosp_28d` | float | hospital hospitalizations in the previous 7 / 28 days |
| `hp_median_wait_prev` | float | median completed wait of the hospital × profile so far |
| `hp_n_hosp_prev` | float | completed hospitalizations of the hospital × profile so far |
| `ersb_throughput_per_day` | float | ERSB discharged cases per day (annual total / 365) |
| `ersb_avg_los` | float | ERSB average length of stay |
| `adm_refusals_28d` | float | admission-unit refusals of the hospital in the previous 28 days |
| `hp_refusal_rate_prev` | float, 0 … 1 | share of refusals among resolved referrals of the hospital × profile so far |
| `hp_n_resolved_prev` | float | resolved referrals of the hospital × profile so far |

`features.json` lists the columns in model order and which are categorical; `categories.json` holds the exact
category levels (fitted on the training fold); numerics are fed as float32, as in training.

## Output

| Column | Meaning |
|---|---|
| `pred_time_days` | AFT location T̂ (a time scale for ranking, not an exact wait; the C-index is computed on it) |
| `p_hospitalized_7d_raw`, `…_14d_raw`, `…_30d_raw` | model probability Φ((ln h − ln T̂) / σ) |
| `p_hospitalized_7d`, `…_14d`, `…_30d` | after the calibrator of that horizon — the quantity the Brier scores below refer to |

`inference.json` carries everything the formula needs (best iteration, distribution, σ, horizons, calibrator
parameters); it is derived from `metrics.json` and `ml/configs/tournament.yaml`.

## Metrics (test month, March 2025, n = 226 046 referrals)

| horizon | Brier (calibrated) | observed hospitalized | mean predicted |
|---|---|---|---|
| 7 d | 0.1212 | 68.4 % | 69.3 % |
| 14 d | 0.1099 | 75.5 % | 75.4 % |
| 30 d | 0.0982 | 81.7 % | 80.9 % |
| **mean** | **0.1098** | | |

C-index (concordance of T̂ with observed time to hospitalization) **0.8476**; mean calibration error 0.0097. All 20
regions have more than 500 test referrals and none does worse than the hospital × profile empirical baseline;
median region Brier 0.0965, worst 0.1370. Two sensitivity checks in `metrics.json`: strict timestamp order (the
104 598 same-day timestamp reversals excluded, 194 386 test rows) gives mean Brier 0.1241 and C-index 0.8331;
deployment-realistic re-censoring (labels known only through 2025-03-01 when training, calibrators not refit) gives
0.1099 and 0.8462. Per-region and per-profile tables, calibration bins and gain-based feature importance
(`queue_hp_prev_day`, `profile_code`, `ersb_throughput_per_day`, `hp_refusal_rate_prev` lead) are in `metrics.json`.

## Load in five lines (native file)

```python
import json, math, numpy as np, pandas as pd, xgboost as xgb
booster = xgb.Booster(); booster.load_model("model.json"); inf = json.load(open("inference.json"))
features = json.load(open("features.json"))["features"]; categories = json.load(open("categories.json"))
X = pd.DataFrame({f: pd.Categorical(df[f].astype("string"), categories=categories[f]) if f in categories else pd.to_numeric(df[f], errors="coerce").astype("float32") for f in features})
T = np.clip(booster.predict(xgb.DMatrix(X, enable_categorical=True), iteration_range=(0, inf["best_iteration"] + 1)), 1e-6, None)
p_raw_14d = 0.5 * np.vectorize(math.erfc)(-(np.log(14) - np.log(T)) / inf["aft"]["scale"] / math.sqrt(2))
```

`predict.py` is this logic plus the calibrators and a CSV CLI: `from predict import load, predict; predict(df, load())`
or `python predict.py --input referrals.csv --output predictions.csv`. It needs only xgboost, pandas and numpy.

## Load in two lines (joblib)

```python
import joblib; from predict import from_bundle, predict
predict(df, from_bundle(joblib.load("bundle.joblib")))   # dict: name, version, model, features, categories, meta, inference, sha256_of_native_file
```

## Limitations (tournament protocol, `docs/model_card.md`; serving contract, `docs/patient-journey-serving-contract.md`)

- Hospitalization-only estimand: refusal is treated as competing censoring and is not predicted. Do not present
  `1 − p` as a refusal or "unresolved" probability, and do not combine these probabilities with `../refusal_risk`
  (a horizon-free probability conditional on a terminal outcome) as if they formed one distribution.
- Probabilities describe associations in historical data, not causal effects: a lower probability at hospital X
  does not mean that moving the patient elsewhere would change the outcome. Not a clinical judgement about a
  patient; the model warns, people decide.
- Cohort of Q1 2025 registrations with outcomes known in hindsight (cutoff 2026-05-13); three months of data, no
  seasonality, one retrospective test month. The deployment-realistic check above shows what fully observed labels
  are worth; queues before 2025-01-01 are not observed.
- Accepted evidence, not a served product feature: the 7 / 14 / 30-day probabilities need a daily referral feed
  and the versioned serving contract (`estimand_id`, `model_version`, `calibration_version`, support state)
  before they appear on screen.
- The model uses the patient's region and city/village; differences across regions reflect historical access and
  must not be used to deprioritise anyone.

## Provenance

| | |
|---|---|
| Source artifact | `artifacts/tournaments/journey-full-confirmation-6b2a-final-20260917/patient_journey--xgboost_aft-final-confirmation--trial-008--70e6db266e97c959` |
| Artifact content sha256 | `9b2b8a9787c029f7488bd19cab4e6cbd7caf8567093f70f7ff9f180d1a86b2f0` |
| `model.json` sha256 | `7f5420e4d6bdd2d5fd4602c920e8149b434fe051e63ba7b01c6c11795bbf37b6` |
| Parameters from | tournament `journey-overnight-6b2a-corrected-20260917`, trial-008, checkpoints `82642e53…1466`, `b7ac901f…e1c0` |
| Config | `ml/configs/tournament.yaml` (label contract, folds, horizons, search space, seed 42) |
| Accepted commit | `a5eb2e9 feat(ml): complete patient journey full-cohort confirmation` |
| Native format | XGBoost JSON as stored in the artifact; the UBJSON form of the same model is 34.1 MB against 35.2 MB (3 % smaller), not worth breaking the byte-identical checksum chain |

Files: `model.json`, `categories.json`, `meta.json`, `metrics.json`, `artifact-manifest.json` (byte-identical to the
artifact), `features.json` and `inference.json` (derived from the artifact and the tournament config), `predict.py`,
`bundle.joblib`, `example.csv.gz` (50 real March 2025 referrals), `example_expected.csv.gz` (their predictions from the
repository code path). Rebuilt by `ml/pipelines/export_models.py`; digests in `../manifest.json`.
