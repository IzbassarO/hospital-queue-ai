# wait_time — days from referral to hospitalization

**Question.** For a planned-hospitalization referral that is not admitted on the day of registration, how many days
will pass between registration and hospitalization?

**Model.** LightGBM regression (405 trees) on `log1p(wait_days)`; predictions are converted back to days and clipped
at zero. Version `20260914-1830`, trained 2026-09-14 on the Ministry of Health open data for Q1 2025.

**Training window.** Referrals registered 2025-01-01 … 2025-02-28 (203 431 rows, median wait 7 days); the number of
boosting rounds was chosen on the last 14 days of that window and the model refitted on the whole window.
Test: referrals registered 2025-03-01 … 2025-03-31 (80 436 rows, median wait 9 days).
Population: `outcome = hospitalized` and `same_day_registration = false`.

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

`features.json` lists the columns in model order and which are categorical; `categories.json` holds the exact
category levels; `display.json` maps region / hospital / profile codes to readable names.

## Output

`pred_wait_days` — expected wait in days (float, ≥ 0). `raw_score()` returns `log1p(days)` for explanations.

## Metrics (test month, March 2025, n = 80 436)

| | MAE, days | median AE | WAPE | within ±7 days | Spearman |
|---|---|---|---|---|---|
| **this model** | **10.51** | 4.04 | **45.1 %** | **65.5 %** | **0.73** |
| median by hospital × profile (best baseline) | 11.12 | 4.00 | 47.7 % | 65.1 % | 0.70 |
| median by profile × patient region | 14.34 | 5.00 | 61.5 % | 61.0 % | 0.56 |
| global median | 19.03 | 5.00 | 81.6 % | 64.4 % | — |

Per-region and per-profile tables, SHAP importance and the `planned_lag_days` ablation are in `metrics.json`.

## Load in five lines (native file)

```python
import json, lightgbm as lgb, numpy as np, pandas as pd
booster = lgb.Booster(model_file="model.txt")
features = json.load(open("features.json"))["features"]; categories = json.load(open("categories.json"))
X = df[features].copy()
for c, levels in categories.items(): X[c] = pd.Categorical(X[c].astype("string").astype(object), categories=levels)
days = np.clip(np.expm1(booster.predict(X.astype({c: "float64" for c in features if c not in categories}), raw_score=True)), 0, None)
```

Or simply `from predict import load, predict; predict(df, load())` — `predict.py` is this exact logic with a CSV CLI.

## Load in two lines (joblib)

```python
import joblib; from predict import from_bundle, predict
predict(df, from_bundle(joblib.load("bundle.joblib")))   # dict: name, version, model, features, categories, meta, sha256_of_native_file
```

## Limitations (model card, `card.json`)

- Два месяца обучения и один месяц проверки: сезонность и изменения год к году не учтены, метрики могут измениться
  при появлении новых данных.
- Ошибка выше всего в офтальмологии, кардиологии и неврологии, где ожидание долгое; в 4 из 20 регионов (Актюбинская,
  Карагандинская, Кызылординская, Северо-Казахстанская области) модель по MAE не лучше медианы по стационару и профилю.
- Прогноз отражает связи в исторических данных: «стационар X → +30 дней» не означает, что перенаправление пациента
  сократит ожидание на столько же.
- Outcomes of training-period referrals are known in hindsight (labels through May 2026), so the evaluation flatters
  long-wait accuracy somewhat; queues before 2025-01-01 are not observed (queue features are lower bounds).
- The model uses the patient's region and city/village; differences across regions reflect historical access and must
  not be used to deprioritise anyone. Not a clinical decision; the model warns, people decide.

## Provenance

| | |
|---|---|
| Source artifact | `artifacts/models/wait_time/20260914-1830` (repository registry, current version) |
| Artifact content sha256 | `74b3df0fd566244e3467c8671d4a090c8a875393354c7ce43bce2262223aef8f` |
| `model.txt` sha256 | `1b987d6a18218e65141c0b1646cefc0ea935f1792e65bf1b8d6123bb10cafe54` |
| Run lineage | legacy artifact trained before run manifests existed; checksum adopted and verified by the registry |
| Config | `ml/configs/models.yaml` (LightGBM defaults, not tuned; seed 42, deterministic) |
| Card | `card.json` is the `wait_time` entry of `ml/configs/model_cards.yaml` (the artifact predates cards) |

Files: `model.txt`, `features.json`, `categories.json`, `meta.json`, `metrics.json`, `display.json`,
`artifact-manifest.json` (all byte-identical to the artifact), `card.json`, `predict.py`, `bundle.joblib`,
`example.csv.gz` (50 real March 2025 referrals), `example_expected.csv.gz` (their predictions from the repository
code path). Rebuilt by `ml/pipelines/export_models.py`; digests in `../manifest.json`.
