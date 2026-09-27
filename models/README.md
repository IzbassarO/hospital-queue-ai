# models/ — the released models as self-contained modules

One folder per frozen model. Each folder works without this repository: the model in its native format, the feature
contract as JSON, a standalone `predict.py` (CSV in → CSV out, plus `load()` / `predict(df)`), a `bundle.joblib`, a
small real example with the predictions the repository itself produced for it, and a README with the question,
inputs, outputs, metrics, training window, limitations and provenance. Dependencies: `lightgbm` (or `xgboost` for the
AFT model), `pandas`, `numpy`; Python 3.10+. About 81 MB in total, every file under 50 MB.

## Index

| Model | Question | Algorithm | Native file | Key metric (time-only validation) | Status |
|---|---|---|---|---|---|
| [`wait_time`](wait_time/) | days from registration to hospitalization | LightGBM regression on log1p(days) | `model.txt` 4.7 MB | MAE 10.5 days vs 11.1 best baseline, March 2025 | accepted |
| [`refusal_risk`](refusal_risk/) | probability that a referral ends in refusal | LightGBM binary classifier | `model.txt` 3.2 MB | ROC-AUC 0.788, calibrated within 1 pp per decile | accepted |
| [`load_forecast`](load_forecast/) | expected registrations and hospitalizations per day, 1 … 14 days ahead | two LightGBM Poisson boosters | `model_registrations.txt` 4.6 MB, `model_hospitalizations.txt` 4.5 MB | WAPE 62.9 % vs 86.4 % seasonal naive (modelled hospital × profile series) | evidence |
| [`patient_journey_aft`](patient_journey_aft/) | probability of hospitalization within 7 / 14 / 30 days | XGBoost AFT survival model | `model.json` 35.2 MB | C-index 0.848, mean Brier 0.110, calibration error 0.010 | accepted |
| [`patient_journey_hazard`](patient_journey_hazard/) | same question, second approach | LightGBM discrete-time hazard | `model.txt` 2.9 MB | C-index 0.803, mean Brier 0.109 | accepted |
| [`flow_quantile`](flow_quantile/) | p10 / p50 / p90 of registrations per day, 1 … 14 days ahead | three LightGBM quantile boosters | `model_registrations_p10/p50/p90.txt` 3.4 + 3.9 + 4.2 MB | WIS80 0.567 vs 0.691 baseline (validation), 0.505 vs 0.765 (final test) | in product |

*in product*: the p10 / p50 / p90 intervals on screen come from this model, through the published bundle rather
than live scoring. *accepted*: validated on time-only folds and frozen; per-referral outputs are not on the current
screens (they need a daily referral feed). *evidence*: the point forecast kept as the comparison for the quantile
chain; not shown. All numbers are on data the models never saw: training January–February 2025, validation on
rolling origins, test in March 2025.

## Use in your system

```bash
pip install lightgbm pandas numpy                 # plus xgboost for patient_journey_aft
cp -r models/refusal_risk .                       # or download that folder alone
python refusal_risk/predict.py --input referrals.csv --output scored.csv
```

```python
import sys; sys.path.insert(0, "refusal_risk")
from predict import load, predict
model = load()                                    # native file + features.json + categories.json (+ inference.json)
scored = predict(referrals, model)                # DataFrame in (one row per referral or series row), DataFrame out
# or from the bundle:  import joblib; from predict import from_bundle
# scored = predict(referrals, from_bundle(joblib.load("refusal_risk/bundle.joblib")))
```

Common input contract: the columns of `features.json`; categorical codes as text (codes like `0011` keep their zeros —
`predict.py` reads them so); missing values allowed everywhere; unseen codes are treated as missing; every value is
what was known at the start of the registration date, or at the forecast origin for series models. `example.csv.gz`
in each folder is a template of real rows and `example_expected.csv.gz` is what the model must return for them.

## Frozen artefacts identified by sha256

`manifest.json` lists every shipped file with its size, sha256 and origin (`artifact (byte-identical)`, `generated`,
`refit`, `hand-written`) and, per model, the provenance: artifact path and content digest, run ids, training windows,
library versions. **A file whose digest differs from the manifest is a different model.** Shipped files are never
edited by hand; they are rebuilt from the checksummed `artifacts/` by the export pipeline, which verifies the source
digests, copies the artifact files byte for byte, derives the loader metadata, builds the bundles, scores the
examples through the repository's own code path and rewrites the manifest:

```bash
PYTHONPATH=ml .venv/bin/python ml/pipelines/export_models.py                 # make models-export (needs artifacts/, data/processed)
PYTHONPATH=ml .venv/bin/python ml/pipelines/export_flow_quantile_models.py   # refit + verify the quantile boosters
cd ml && ../.venv/bin/python -m pytest tests/test_models_release.py          # part of make ml-test; no database
```

Running the export twice gives byte-identical files (gzip without timestamps, canonical JSON, fixed sampling seed);
the joblib bundles embed the boosters' own serialisation and stay identical as long as the lightgbm / xgboost versions
do not change. Built with Python 3.14.7, lightgbm 4.7.0, xgboost 3.4.1, pandas 3.0.5, numpy 2.5.3, joblib 1.6.0.
The native files are the portable form (LightGBM text models load in any 4.x; XGBoost JSON loads in the saving
version and newer). `bundle.joblib` is a Python pickle of a plain dict — `name`, `version`, `model` (the booster, or a
dict of boosters), `features`, `categories`, `meta`, `inference` where the model has one, `sha256_of_native_file` —
for the same library major versions. To check a download:

```python
import hashlib, json, pathlib
manifest = json.load(open("models/manifest.json"))
changed = [p for p, e in manifest["files"].items() if hashlib.sha256(pathlib.Path("models", p).read_bytes()).hexdigest() != e["sha256"]]
```

`ml/tests/test_models_release.py` (run by `make ml-test`) checks that the manifest matches the folder, that the
artifact copies are byte-identical to their checksummed artifacts, and that `predict.py` — run as a subprocess with
no repository code on the path — and the joblib bundle both reproduce `example_expected.csv.gz` within 1e-6
(relative for counts).

## Where the flow quantile model stands

The accepted run `flow-quantile-6b2b2-real-v1` kept its evaluation frame, not its boosters, and the product reads
its published forecasts (`seed/operational_intelligence.json.gz`, 225 680 rows, 222 964 of them with raw p10 / p50 /
p90 and a separately calibrated interval). `flow_quantile/` therefore holds a deterministic refit of the final-origin
(2025-03-17) boosters from the same code, configuration, data and seed, exported only after its predictions were
compared with the published raw quantiles: over all 47 782 directly supported (series, horizon) cells and a
200-series hospital sample the maximum difference is 0.0 (`flow_quantile/verification.json`). Only the
`registrations` boosters are shipped; the `cohort_hospitalizations` ones were refit and verified the same way
(difference 0.0) and can be added with `--ship-targets`. They give raw quantiles; the fallback for series without
direct support, the hierarchy and the calibrated interval bounds live in the repository and in the bundle, not here.

## What this folder is not

- Not the training pipelines or the data: `ml/` with `make train`, `make tournament`, `make flow-quantile` rebuilds
  every model from the Ministry of Health open data (`docs/data.md`); `artifacts/` and `data/` are not committed.
- Not the product logic around the models: pressure signals, the region share fallback, calibrated intervals,
  explanations and the specialist's decision log are in `backend/`, `ml/hqai_ml/flow_forecast/` and the published
  bundles in `seed/`.
- Not a clinical tool. The outputs are flow and waiting statistics for a specialist to review; nothing here
  decides about a patient. The model warns. People decide.
