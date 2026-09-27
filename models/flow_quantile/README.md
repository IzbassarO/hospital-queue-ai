# flow_quantile — p10 / p50 / p90 of daily referral registrations, 1 … 14 days ahead

**Question.** For a hospital × profile or region × profile series, how many referrals will be registered on each of
the next 14 days — as an 80 % interval (p10, p90) around a median (p50) rather than a single number?

**Where the model stands.** This is the model behind the intervals in the product, but the product does not run it.
The UI and API read the published bundle `seed/operational_intelligence.json.gz` (publication
`operational-intelligence-slice5-final-test-2025-03-17-v1`, identity `43da33ec…5cfd`): 225 680 forecast rows, of which
222 964 carry `raw_quantiles` p10 / p50 / p90 for a series, target and horizon (the rest are unsupported series) plus a
separately calibrated interval. The accepted
run `flow-quantile-6b2b2-real-v1` kept its evaluation frame, not its boosters (`fit_quantile_target` in
`ml/hqai_ml/flow_forecast/quantile.py` hands them to the caller only). The three files here are a **deterministic
refit** with the same code, configuration, processed data, seed and thread count
(`ml/pipelines/export_flow_quantile_models.py`), verified before anything was written: over all 47 782 directly
supported (series, horizon) cells of the final-test origin, and over a random sample of 200 hospital × profile series
(2 800 cells), the maximum absolute difference to the published raw p10, p50 and p90 is **0.0** (tolerance 1e-3
relative; `verification.json`). The `cohort_hospitalizations` boosters were refit and matched the same way but are
not shipped, to keep `models/` small; `--ship-targets registrations cohort_hospitalizations` adds them (≈ 11 MB).

**Model.** Three global LightGBM boosters with the `quantile` objective (α = 0.10, 0.50, 0.90), 400 rounds each,
63 leaves, learning rate 0.05, feature and bagging fraction 0.8, L2 1.0, at least 100 rows per leaf, seed 42,
deterministic, 4 threads (thread count is execution metadata; the same count gives identical trees). Training frame
at the final-test origin 2025-03-17: every directly supported series — 1 987 hospital × profile series with at least
28 days of history and a mean of at least one registration per day, plus all 1 426 region × profile series — with
every cutoff from day index 6 to the day before the origin and every horizon 1 … 14 whose target date is on or
before the origin; nothing after the origin is seen. The `level` feature lets one booster serve both levels.

## Input columns

One row per (series, forecast origin, horizon). Lag and rolling features are computed from the registrations series
with days ≤ the origin only; the construction is `hqai_ml.features.load.build_rows` (`example.csv.gz` shows 42
rows at origin 2025-03-17). The `target` column (or `--target`) selects the booster set; only `registrations` is
shipped.

| Column | Type | Meaning |
|---|---|---|
| `level` | string: `hospital` / `region` | series level |
| `org_code` | string code | hospital, or `__region__` for region series |
| `region_code` | string code | region |
| `profile_code` | string code | hospitalization profile |
| `horizon` | float, 1 … 14 | days ahead of the origin |
| `lag_1`, `lag_2`, `lag_3`, `lag_7`, `lag_14` | float | registrations k days before origin + 1 (lag_1 = origin day) |
| `roll_mean_7`, `roll_mean_14`, `roll_mean_28` | float | mean registrations over the last w days ending at the origin |
| `same_weekday_last` | float | latest observed value on the target day's weekday |
| `queue_at_origin` | float | end-of-day queue length of the series at the origin |
| `target_weekday` | float, 1 … 7 | ISO weekday of the target day |
| `target_is_holiday` | float, 0 / 1 | target day in the public-holiday list (incl. transferred days off) |
| `target_day_index` | float | target day as days since 2025-01-01 |

`categories_registrations.json` holds the category levels of the directly supported series only. A hospital × profile
series that was not directly supported at the origin is not scored by these boosters in the product: it receives the
region × profile quantiles scaled by its historical share (`prediction_source = REGION_PROFILE_FALLBACK`), and a
series with too little history is `UNSUPPORTED`. That fallback and hierarchy logic (`hqai_ml.flow_forecast`) is not
part of this module; feeding such a series here gives a prediction with `org_code` treated as missing.

## Output

| Column | Meaning |
|---|---|
| `p10`, `p50`, `p90` | raw model quantiles — the published scientific evidence; may be negative or cross (final test, hospital level: 6.6 % of cells negative, 7.9 % crossing) |
| `p10_repaired`, `p50_repaired`, `p90_repaired` | max(0) then cumulative maximum across the three — the serving diagnostic variant; never governs evaluation |

National values in the product are the sum of the region quantiles for a profile (labelled a proxy, not valid
quantiles) and are not produced here.

## Metrics (registrations, raw quantiles, macro-average over series; `summary.json` of the accepted run)

| phase | level | | mean pinball | WIS80 | 80 % interval coverage |
|---|---|---|---|---|---|
| validation, origins 16.02 / 23.02 / 02.03 | hospital × profile (6 537 series) | **model** | **0.283** | **0.567** | 50.9 % |
| | | baseline | 0.346 | 0.691 | 56.9 % |
| validation | region × profile (1 426) | **model** | **0.675** | **1.349** | 75.9 % |
| | | baseline | 0.822 | 1.644 | 77.5 % |
| final test, origin 17.03 | hospital × profile (6 537) | **model** | **0.252** | **0.505** | 29.9 % |
| | | baseline | 0.382 | 0.765 | 55.9 % |
| final test | region × profile (1 426) | **model** | **0.660** | **1.320** | 59.8 % |
| | | baseline | 1.299 | 2.598 | 74.5 % |

Baseline: recent seasonal average with horizon-specific empirical residual quantiles (28-day window). Hospital-level
rows include the ≈ 70 % of hospital × profile series served by the region fallback. The retention decision used
validation only (final test never selects or calibrates): both retained, no automatic promotion. The raw 80 %
intervals are too narrow — 29.9 % coverage on the final test at hospital level — and the product never shows them
raw: the separate temporal calibration step (run `flow-calibration-6b2b2b-real-v1`, symmetric conformal-style
expansion on origin-legal residuals) brings hospital registrations to 83.0 % on validation and 69.9 % on the final
test, and the bundle carries those bounds as `calibrated_uncertainty` next to the untouched `raw_quantiles`. These
boosters give raw quantiles only.

## Load in five lines (native files)

```python
import json, lightgbm as lgb, pandas as pd
boosters = {q: lgb.Booster(model_file=f"model_registrations_{q}.txt") for q in ("p10", "p50", "p90")}
features = json.load(open("features.json"))["features"]; categories = json.load(open("categories_registrations.json"))
X = rows[features].copy()
for c, levels in categories.items(): X[c] = pd.Categorical(X[c].astype("string").astype(object), categories=levels)
quantiles = {q: b.predict(X.astype({c: "float64" for c in features if c not in categories})) for q, b in boosters.items()}
```

Or `from predict import load, predict; predict(rows, load())` (rows carry a `target` column) — `predict.py` is this
exact logic plus the repaired variant and a CSV CLI (`python predict.py --input rows.csv --output out.csv --target
registrations`). There is no `bundle.joblib`: the three native files with `categories_registrations.json` and
`features.json` are the whole contract, and `predict.load()` is the loader.

## Reproducing

```bash
make ingest                                    # MoH raw CSV (16 GB, from the organisers) -> data/processed/*.parquet
make flow-quantile PROFILE=laptop              # accepted protocol: 3 validation origins + final test, both targets
                                               #   -> artifacts/flow_quantile/<run-id>/ (evaluation frames, summary)
PYTHONPATH=ml .venv/bin/python ml/pipelines/export_flow_quantile_models.py
                                               # refit the final-origin boosters, verify against the accepted run's
                                               #   published raw quantiles, write here only if within tolerance (~3 min)
```

`ml/configs/flow_quantile.yaml` (protocol, origins, 400 rounds, quantiles) and `ml/configs/models.yaml` (LightGBM
parameters, lags, rolling windows, holidays) are read unchanged; `meta.json` records the parameters actually used.

## Limitations (`docs/flow-quantile-forecast.md`, `card.json` of `../load_forecast`)

- 90 observed days: no annual seasonality, finite-sample residual evidence; a retrospective origin 2025-03-17, not
  a live forecast or a current hospital condition. Holidays (the Nauryz week) are the main error source.
- Raw quantiles are reported as they are — negative values and crossing are shown, not hidden; the repaired variant
  is a display projection, not better evidence. Raw coverage is far below the nominal 80 %.
- Registrations are flow counts; nothing here measures beds or physical resources. `cohort_hospitalizations` (not
  shipped) counts hospitalization events of referrals registered in Q1 only, left-censored in early January.
- Hospital forecasts are not reconciled with region forecasts; national values are proxies. Series without direct
  support need the fallback logic that lives in the repository, not in this folder.

## Provenance

| | |
|---|---|
| Refit of | run `flow-quantile-6b2b2-real-v1`, origin artifact `artifacts/flow_quantile/flow-quantile-6b2b2-real-v1/origins/final_test-2025-03-17-f511b8990d57` (`evaluation.parquet`) |
| Run identities | scientific `f55dff24…ddde`, dataset `49d7e695…7dc0`, config `3d0e7a46…0a74`, code `e3c3bb7a…d225` (`meta.json`) |
| `model_registrations_p10.txt` sha256 | `f5f94213f0b9d8d47ceb87db3f88cc0a7a6ecd1d1441fa0ace95fd4daf32a820` |
| `model_registrations_p50.txt` sha256 | `ade945e3b87dc6acb18313ef1b2dca20e3e2b8b7d234a8a737e7a279341ddd2e` |
| `model_registrations_p90.txt` sha256 | `f959b971b2771e66c68e7d984073800fccddd077fda5afbf7ae5b3b6569778ec` |
| Verification | `verification.json`: 47 782 cells and a 200-series hospital sample per target, max abs / relative difference 0.0 |
| Published forecasts | `seed/operational_intelligence.json.gz` (`forecasts[].raw_quantiles`, `support_status = DIRECT_SUPPORTED` for the series these boosters cover); source `artifacts/operational_intelligence/operational-intelligence-slice5-final-test-2025-03-17-v1/` |

Files: `model_registrations_p10.txt`, `model_registrations_p50.txt`, `model_registrations_p90.txt`,
`categories_registrations.json`, `features.json`, `meta.json`, `verification.json`, `predict.py`, `example.csv.gz`
(42 origin rows of directly supported series), `example_expected.csv.gz` (their raw quantiles from the refit boosters,
equal to the published values). Rebuilt by `ml/pipelines/export_flow_quantile_models.py`; digests in `../manifest.json`.
