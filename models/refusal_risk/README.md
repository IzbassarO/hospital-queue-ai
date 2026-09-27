# refusal_risk — probability that a referral ends in refusal

**Question.** For a planned-hospitalization referral, what is the probability that it ends in a refusal rather than
a hospitalization?

**Model.** LightGBM binary classifier (212 trees, log-loss). Version `20260914-1831`, trained 2026-09-14 on the
Ministry of Health open data for Q1 2025.

**Training window.** Referrals registered 2025-01-01 … 2025-02-28 with a terminal outcome (538 507 rows, refusal rate
11.1 %); the number of boosting rounds was chosen on the last 14 days of that window and the model refitted on the
whole window. Test: referrals registered 2025-03-01 … 2025-03-31 (224 661 rows, refusal rate 10.9 %).
Population: `outcome in (hospitalized, refused)`.

## Input columns

One row per referral. Every value is as of the **start of the registration date** (aggregates up to the previous
day; outcome-derived statistics only from referrals resolved strictly before that date). Missing values are allowed
in every column; unseen category codes are treated as missing.

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
| `day_of_window` | float | days since 2025-01-01 |
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
category levels; `display.json` maps region / hospital / profile codes to readable names.

## Output

`pred_refusal_prob` — probability of refusal in [0, 1]. `raw_score()` returns the log-odds for explanations.
The product flags a referral as high risk at `pred_refusal_prob >= 0.25` (`ml/configs/serving.yaml`).

## Metrics (test month, March 2025, n = 224 661, refusal rate 10.9 %)

| | ROC-AUC | PR-AUC | Brier | precision in top 10 % | recall in top 10 % |
|---|---|---|---|---|---|
| **this model** | **0.788** | **0.384** | **0.0823** | **39.9 %** | **36.5 %** |
| refusal rate by hospital × profile (best baseline) | 0.761 | 0.322 | 0.0863 | 35.7 % | 32.6 % |
| refusal rate by profile × patient region | 0.714 | 0.255 | 0.0904 | 30.5 % | 27.9 % |
| global rate | 0.500 | 0.109 | 0.0974 | 9.4 % | 8.6 % |

In every predicted-probability decile the mean prediction and the observed rate differ by at most 1 percentage point
(`calibration_model` in `metrics.json`, together with per-region / per-profile tables and SHAP importance).

## Load in five lines (native file)

```python
import json, lightgbm as lgb, numpy as np, pandas as pd
booster = lgb.Booster(model_file="model.txt")
features = json.load(open("features.json"))["features"]; categories = json.load(open("categories.json"))
X = df[features].copy()
for c, levels in categories.items(): X[c] = pd.Categorical(X[c].astype("string").astype(object), categories=levels)
prob = 1 / (1 + np.exp(-booster.predict(X.astype({c: "float64" for c in features if c not in categories}), raw_score=True)))
```

Or simply `from predict import load, predict; predict(df, load())` — `predict.py` is this exact logic with a CSV CLI.

## Load in two lines (joblib)

```python
import joblib; from predict import from_bundle, predict
predict(df, from_bundle(joblib.load("bundle.joblib")))   # dict: name, version, model, features, categories, meta, sha256_of_native_file
```

## Limitations (model card, `card.json`)

- Калибровка хорошая (расхождение прогноза и факта по децилям не более 1 п.п.), но ранжирование слабее в
  Мангистауской, Акмолинской и Актюбинской областях (ROC-AUC 0,71–0,72).
- Модель использует регион и тип местности пациента: различия прогнозов между регионами отражают исторический доступ к
  помощи и не должны использоваться для понижения приоритета пациентов из какого-либо региона.
- Метки обучающего периода известны задним числом; в реальной эксплуатации часть направлений на дату переобучения ещё
  не завершена, поэтому оценка точности несколько оптимистична.
- Two months of training data and one test month: no seasonality, no year-over-year validation. Associations, not
  causes. Not a clinical decision about a patient; the model warns, people decide.

## Provenance

| | |
|---|---|
| Source artifact | `artifacts/models/refusal_risk/20260914-1831` (repository registry, current version) |
| Artifact content sha256 | `c674f3a281f19316f5153c3c488ed73eebf925360fa232ff02e5cb82ada276a2` |
| `model.txt` sha256 | `e71246027ece17eb88709e6adea0a36df03dc3b743546bc1ea1dd2ad223519c6` |
| Run lineage | legacy artifact trained before run manifests existed; checksum adopted and verified by the registry |
| Config | `ml/configs/models.yaml` (LightGBM defaults, not tuned; seed 42, deterministic) |
| Card | `card.json` is the `refusal_risk` entry of `ml/configs/model_cards.yaml` (the artifact predates cards) |

Files: `model.txt`, `features.json`, `categories.json`, `meta.json`, `metrics.json`, `display.json`,
`artifact-manifest.json` (all byte-identical to the artifact), `card.json`, `predict.py`, `bundle.joblib`,
`example.csv.gz` (50 real March 2025 referrals), `example_expected.csv.gz` (their predictions from the repository
code path). Rebuilt by `ml/pipelines/export_models.py`; digests in `../manifest.json`.
