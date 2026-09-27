# load_forecast — expected daily registrations and hospitalizations, 1 … 14 days ahead

**Question.** For a hospital × profile or region × profile series, how many referrals will be registered and how
many hospitalizations will happen on each of the next 14 days?

**Model.** Two global LightGBM Poisson boosters (400 rounds each), one per target: `model_registrations.txt` and
`model_hospitalizations.txt`. Direct multi-horizon: one row per (series, forecast origin = last known day, horizon
h ∈ 1 … 14), the booster predicts the count on day origin + h from features known on the origin day. The `level`
column is a feature, so one booster serves both hospital and region series. Version `20260914-1918`, trained
2026-09-14 on the Ministry of Health open data for Q1 2025.

**Training window.** Series selection on 2025-01-01 … 2025-02-28 (hospital × profile series with a train-period mean
of ≥ 1 registration per day are modelled: 2 023 of 6 537; the other 4 514 receive their region × profile forecast
scaled by their train-period share, `series.json`; all 1 426 region × profile series are modelled). Rolling-origin
backtest at origins 2025-03-03, 03-10, 03-17; the shipped boosters are the final fit on all data through
2025-03-31.

## Input columns

One row per (series, origin, horizon). Lag and rolling features are computed from the **target** series (registrations
for the registrations booster, hospitalizations for the hospitalizations booster), so rows for the two targets differ;
the `target` column selects the booster. All values use days ≤ the origin only.

| Column | Type | Meaning |
|---|---|---|
| `level` | string: `hospital` / `region` | series level |
| `org_code` | string code | hospital, or `__region__` for region series |
| `region_code` | string code | region |
| `profile_code` | string code | hospitalization profile |
| `horizon` | float, 1 … 14 | days ahead of the origin |
| `lag_1`, `lag_2`, `lag_3`, `lag_7`, `lag_14` | float | target value k days before origin + 1 (lag_1 = origin day) |
| `roll_mean_7`, `roll_mean_14`, `roll_mean_28` | float | mean of the target over the last w days ending at the origin |
| `same_weekday_last` | float | latest observed target value on the target day's weekday |
| `queue_at_origin` | float | end-of-day queue length of the series at the origin |
| `target_weekday` | float, 1 … 7 | ISO weekday of the target day |
| `target_is_holiday` | float, 0 / 1 | target day in the public-holiday list (`meta.json`, incl. transferred days off) |
| `target_day_index` | float | target day as days since 2025-01-01 |

Use the same construction as `hqai_ml.features.load.build_rows` (`example.csv.gz` shows 25 rows per target at origin
2025-03-31). Missing values are allowed; unseen category codes are treated as missing.

## Output

`pred` — expected daily count for the row's target (float ≥ 0, Poisson mean). No queue path is derived: in the
backtest the derived queue was worse than keeping the last known queue.

## Metrics (rolling-origin backtest, 3 origins × 14 days, WAPE)

| target | series (n cells) | **model** | seasonal naive | mean 28 d |
|---|---|---|---|---|
| registrations | hospital × profile, modelled (84 966) | **62.9 %** | 86.4 % | 102.2 % |
| registrations | hospital × profile, fallback (189 588) | **119.7 %** | 148.1 % | 155.0 % |
| registrations | region × profile (59 892) | **49.3 %** | 61.7 % | 86.8 % |
| hospitalizations | hospital × profile, modelled | **68.5 %** | 91.1 % | 108.2 % |
| hospitalizations | hospital × profile, fallback | **129.9 %** | 151.4 % | 161.4 % |
| hospitalizations | region × profile | **56.1 %** | 65.7 % | 89.9 % |

The model beats seasonal naive at every level and in every origin × horizon-bucket cell (`beats_seasonal_naive`,
`per_origin`, `by_region`, `by_top_hospital`, `queue`, `calendar_check` in `metrics.json`).

## Load in five lines (native file)

```python
import json, lightgbm as lgb, pandas as pd
booster = lgb.Booster(model_file="model_registrations.txt")          # or model_hospitalizations.txt
features = json.load(open("features.json"))["features"]; categories = json.load(open("categories.json"))
X = rows[features].copy()
for c, levels in categories.items(): X[c] = pd.Categorical(X[c].astype("string").astype(object), categories=levels)
expected = booster.predict(X.astype({c: "float64" for c in features if c not in categories}))
```

Or simply `from predict import load, predict; predict(rows, load())` (rows carry a `target` column) — `predict.py` is
this exact logic with a CSV CLI (`--target` when the CSV has no such column).

## Load in two lines (joblib)

```python
import joblib; from predict import from_bundle, predict
predict(rows, from_bundle(joblib.load("bundle.joblib")))   # dict; `model` maps target -> booster
```

## Limitations (model card, `card.json`)

- Ошибки на уровне отдельного стационара высоки у любого метода, потому что дневные числа малы; для малых рядов прогноз
  стационара — доля прогноза региона.
- Главный источник ошибок — праздники (неделя Наурыза): в обучении лишь несколько праздничных дней, календарь праздников
  ведётся вручную и должен включать переносы выходных.
- Прогнозы стационаров не согласованы с прогнозами регионов. Производный прогноз очереди не показывается: в бэктесте он
  хуже, чем последнее известное значение очереди.
- Three months of data, one retrospective origin set; nothing before 2025-01-01 is observed. Registrations and
  hospitalizations are flow counts; nothing here measures beds or physical resources.

## Provenance

| | |
|---|---|
| Source artifact | `artifacts/models/load_forecast/20260914-1918` (repository registry, current version) |
| Artifact content sha256 | `f7a12afa660cfdcaf02bd374b93239c92bab27061c9234171d6ae1931225eb5a` |
| `model_registrations.txt` sha256 | `8ef35556f50650d953262bc16871fb6a5c65b09d760f3a368f4e1c73a6eda7ad` |
| `model_hospitalizations.txt` sha256 | `290f7851d838e165a25e8c75f348473496edc65f5805627052095f7bfd7c69ba` |
| Run lineage | legacy artifact trained before run manifests existed; checksum adopted and verified by the registry |
| Config | `ml/configs/models.yaml` (`load_forecast` section: lags, rolling windows, holidays, 400 Poisson rounds) |
| Card | `card.json` is the `load_forecast` entry of `ml/configs/model_cards.yaml` (the artifact predates cards) |

Files: `model_registrations.txt`, `model_hospitalizations.txt`, `features.json`, `categories.json`, `meta.json`,
`metrics.json`, `series.json`, `artifact-manifest.json` (all byte-identical to the artifact), `card.json`,
`predict.py`, `bundle.joblib`, `example.csv.gz`, `example_expected.csv.gz`. Rebuilt by
`ml/pipelines/export_models.py`; digests in `../manifest.json`.
