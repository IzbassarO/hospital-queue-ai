# ml

Python package `hqai_ml` plus runnable pipelines and configuration.

```
ml/
  hqai_ml/
    ingest/       raw data → Parquet → Postgres
    features/     referral features (A, B), series panels and horizon rows (C)
    models/       wait_time (A), refusal_risk (B), load_forecast (C)
    causal/       placeholder
    evaluation/   temporal split, metrics, backtest, report
    explain/      SHAP explanations with Russian templates
    registry/     run manifests, checkpoints and checksummed versioned artifacts
    serving/      serving marts for the API (SQL run inside Postgres; docs/api.md)
  pipelines/
    ingest.py     make ingest
    baseline.py   make baseline → reports/01_baseline.md
    train.py      make train    → artifacts/models/, reports/02_models.md  (--model to run one)
    predict.py    make predict  → pred_referral, pred_daily_forecast, model_registry (then build_marts.py)
    build_marts.py make marts   → mart_hospital_profile_status, mart_region_profile_status, mart_area_status
  configs/
    serving.yaml  as-of date, windows, load_index weights, status / alert thresholds, recommendation rule
    ingest.yaml   pipeline parameters (window, date ranges, thresholds)
    regions.yaml  region code dictionary — generated, reviewed by hand
    org_matches.yaml       manual hospital ↔ ERSB match overrides
    models.yaml            split, LightGBM defaults, forecast settings, holidays
    explain_templates.yaml Russian sentence templates for explanations
```

Pipelines are run with `PYTHONPATH=ml` (the Makefile sets it).

## Reproducible training runs

`make train` still trains all three current models. Each invocation now creates
`artifacts/runs/<run_id>/run.json`; completed model checkpoints point to immutable directories under
`artifacts/models/`. Both locations are ignored by Git.

```bash
make train ARGS="--plan --resource-profile laptop"
make train MODEL=wait_time ARGS="--run-id wait-baseline-01 --resource-profile laptop"
make train ARGS="--resume 20260916T020000Z-abc123def456 --resource-profile overnight"
make train ARGS="--resource-profile overnight --model-threads 6 --parallel-trials 2 --process-concurrency 2"
```

`--plan` is read-only: it shows which models would train, data/config/code identities, resource limits,
checkpoint location, and (with `--resume`) which completed checkpoints are reusable. Resume requires the same
models, data, normalized YAML configuration, source code, temporal protocol, hyperparameters and effective
resource configuration. Incomplete units are retrained. Completed units are reused only after their complete
artifact manifest passes SHA256 verification.

The run manifest records model families/targets, UTC lifecycle timestamps, Git commit and dirty flag, semantic
processed-data identity, input-manifest and processed-file content checksums, normalized configuration identity,
ML source identity,
temporal boundaries and availability rules, seeds, effective resources, implementation versions, metrics,
baselines, artifact locations/checksums, evaluation state and sanitized failure information. Identity fields are
fixed when a run starts. Only status, end time, checkpoints, metrics, baselines, artifacts, evaluation and failure
fields may change while it runs; a completed manifest is immutable through the registry API.

`laptop` defaults to conservative threads and one trial/process. `overnight` increases bounded parallelism without
nesting one worker per CPU. Explicit overrides are capped at the detected logical CPU count, and BLAS/OpenMP
limits are set before numerical libraries load.

Python, NumPy and LightGBM seeds are centralized and recorded. This supports reproducible experiment identity and
controlled reruns; it does **not** promise bit-for-bit numerical equality across operating systems, CPU
architectures, thread counts or library versions.

Every new model directory has `artifact-manifest.json`, containing sorted per-file sizes/SHA256 values and one
aggregate content identity. Loading and PostgreSQL registry publication verify it first and fail on corruption.
Existing pre-6B.1 artifacts receive a checksum sidecar on first load and remain usable as explicitly
`legacy_unattributed`; only new artifacts with complete passed-evaluation lineage can be registered as fully
attributed.
