# patient_journey_hazard — probability that a referral is hospitalized within 7 / 14 / 30 days (discrete hazard)

**Question.** For a planned-hospitalization referral, as of its registration date, what is the probability that the
patient is hospitalized within 7, 14 and 30 days? Refusals and still-open referrals are censoring, not a second
outcome: `1 − p` is "not hospitalized by then", never a refusal probability. Same question, cohort, features and
test set as `../patient_journey_aft`; a second modelling approach the tournament retained alongside it.

**Model.** LightGBM binary classifier (48 leaves, learning rate 0.062, min 65 rows per leaf, 271 rounds) on
referral × interval rows. Time since registration is cut into nine intervals with edges 0, 1, 3, 7, 14, 30, 60,
120, 240, 500 days; a training referral contributes one row per interval it enters, labelled 1 in the interval where
it is hospitalized, and stops contributing once refused or censored. The interval index is a categorical feature
`time_interval` (`"0"` … `"8"`), so the booster predicts the hazard h_k = P(hospitalized in interval k | not before).
The probability by an edge is the cumulative incidence Σ S_{k−1} · h_k with survival S_k = S_{k−1} · (1 − h_k);
7, 14 and 30 days are edges (after intervals 2, 3 and 4). A per-horizon isotonic calibrator fitted on the calibration
week is applied on top. Candidate `discrete_hospitalization_hazard`, trial-030 of the patient-journey tournament,
refitted on the full eligible cohort in run `journey-full-confirmation-6b2a-final-20260917`.

**Training window.** Fold `q1_final` of the confirmation: train 2025-01-01 … 02-14 (early stopping on
02-15 … 02-21 kept all 271 rounds), calibrators on 02-22 … 02-28, test = referrals registered 2025-03-01 … 03-31
(226 046). Outcomes are observed through the fixed label cutoff 2026-05-13. Eligible cohort 767 084 of 767 130
referrals (45 events dated before registration and one dual-event conflict excluded; same-day registrations modelled
at a positive 0.5-day duration).

**Why this file.** As for the AFT model: of the two directories per finalist in the confirmation run, `q1_final`
(`…--d8872d7434eb1e26`) is the one whose test metrics `docs/project-evidence-index.md` cites (C-index 0.802645, mean
Brier 0.108575); the `q1_fold_1` sibling (January training, 15–28 February test) stays in `artifacts/` as evidence.
The tournament's decision is "retain both pending product/serving tradeoff": this model has the best principal Brier
and the best Brier under the strict timestamp-order sensitivity; the AFT is better on C-index, calibration error,
deployment-realistic Brier, worst region and runtime.

## Input columns

One row per referral. Every value is as of the **start of the registration date** (aggregates up to the previous
day; outcome-derived statistics only from referrals resolved strictly before that date). Missing values are allowed
in every column; unseen category codes are treated as missing. `day_of_window` (calendar position) is deliberately
not a feature. `time_interval` is added by the predictor, not by the caller.

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
| `p_hospitalized_7d_raw`, `…_14d_raw`, `…_30d_raw` | cumulative incidence from the interval hazards |
| `p_hospitalized_7d`, `…_14d`, `…_30d` | after the isotonic calibrator of that horizon — the quantity the Brier scores below refer to |

`inference.json` carries everything the recursion needs (interval edges, number of iterations, horizons, calibrator
thresholds); it is derived from `metrics.json` and `ml/configs/tournament.yaml`.

## Metrics (test month, March 2025, n = 226 046 referrals)

| horizon | Brier (calibrated) | observed hospitalized | mean predicted |
|---|---|---|---|
| 7 d | 0.1198 | 68.4 % | 69.3 % |
| 14 d | 0.1082 | 75.5 % | 75.4 % |
| 30 d | 0.0977 | 81.7 % | 80.9 % |
| **mean** | **0.1086** | | |

C-index **0.8026**; mean calibration error 0.0107. All 20 regions have more than 500 test referrals and none does
worse than the hospital × profile empirical baseline; median region Brier 0.0969, worst 0.1391. Sensitivity checks in
`metrics.json`: strict timestamp order (the 104 598 same-day timestamp reversals excluded, 194 386 test rows) gives
mean Brier 0.1224 and C-index 0.7837; deployment-realistic re-censoring (labels known only through 2025-03-01 when
training, calibrators not refit) gives 0.1187 and 0.7603 — the clearest gap to the AFT model (0.1099 and 0.8462),
which is why neither was promoted alone. Gain-based importance is led by `org_code`, `time_interval`,
`profile_code`, `queue_hp_prev_day` and `icd3`.

## Load in a few lines (native file)

```python
import json, lightgbm as lgb, numpy as np, pandas as pd
booster = lgb.Booster(model_file="model.txt"); inf = json.load(open("inference.json")); edges = inf["hazard"]["time_bins"]
features = json.load(open("features.json"))["features"]; categories = json.load(open("categories.json"))
X = pd.DataFrame({f: pd.Categorical(df[f].astype("string"), categories=categories[f]) if f in categories else pd.to_numeric(df[f], errors="coerce").astype("float32") for f in features})
survival, p_raw = np.ones(len(X)), {0: np.zeros(len(X))}
for k, end in enumerate(edges[1:]):
    X["time_interval"] = pd.Categorical([str(k)] * len(X), categories=[str(i) for i in range(len(edges) - 1)])
    hazard = booster.predict(X, num_iteration=inf["hazard"]["num_iteration"])
    p_raw[end] = p_raw[edges[k]] + survival * hazard; survival = survival * (1 - hazard)   # p_raw[7], p_raw[14], p_raw[30]
```

`predict.py` is this logic plus the calibrators and a CSV CLI: `from predict import load, predict; predict(df, load())`
or `python predict.py --input referrals.csv --output predictions.csv`. It needs only lightgbm, pandas and numpy.

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
  seasonality, one retrospective test month. Under realistic label availability the model loses more than the AFT
  (see above); queues before 2025-01-01 are not observed.
- Accepted evidence, not a served product feature: the 7 / 14 / 30-day probabilities need a daily referral feed
  and the versioned serving contract (`estimand_id`, `model_version`, `calibration_version`, support state)
  before they appear on screen.
- The model uses the patient's region and city/village; differences across regions reflect historical access and
  must not be used to deprioritise anyone.

## Provenance

| | |
|---|---|
| Source artifact | `artifacts/tournaments/journey-full-confirmation-6b2a-final-20260917/patient_journey--discrete_hospitalization_hazard-final-confirmation--trial-030--d8872d7434eb1e26` |
| Artifact content sha256 | `db678bfa061510655c984746b22425f15cc45c34144469d376fa5bc0865c2012` |
| `model.txt` sha256 | `2a355548b82990d1e11f4ea98d4d622409bf7f3ce22b72230aac9d3c09e486b8` |
| Parameters from | tournament `journey-overnight-6b2a-corrected-20260917`, trial-030, checkpoints `69698cea…1eb5`, `93127e94…9169` |
| Config | `ml/configs/tournament.yaml` (label contract, folds, horizons, interval edges, search space, seed 42) |
| Accepted commit | `a5eb2e9 feat(ml): complete patient journey full-cohort confirmation` |

Files: `model.txt`, `categories.json`, `meta.json`, `metrics.json`, `artifact-manifest.json` (byte-identical to the
artifact), `features.json` and `inference.json` (derived from the artifact and the tournament config), `predict.py`,
`bundle.joblib`, `example.csv.gz` (the same 50 real March 2025 referrals as the AFT module), `example_expected.csv.gz`
(their predictions from the repository code path). Rebuilt by `ml/pipelines/export_models.py`; digests in
`../manifest.json`.
