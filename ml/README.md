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

`make train` trains all three model candidates but does not change the serving selection. Each invocation creates
`artifacts/runs/<run_id>/run.json`; independently atomic unit checkpoints live under
`artifacts/runs/<run_id>/checkpoints/`, and completed model checkpoints may point to immutable directories under
`artifacts/models/`. These locations are ignored by Git.

```bash
make train ARGS="--plan --resource-profile laptop"
make train MODEL=wait_time ARGS="--run-id wait-baseline-01 --resource-profile laptop"
make train ARGS="--resume 20260916T020000Z-abc123def456 --resource-profile overnight"
make train ARGS="--resume 20260916T020000Z-abc123def456 --promote"
```

`--plan` is read-only: it shows which models would train, data/config/code identities, resource limits,
checkpoint location, and (with `--resume`) which completed checkpoints are reusable. Resume requires the same
models/candidates, data, normalized YAML configuration, source code, temporal protocol, scientific
hyperparameters, seeds and relevant implementation versions. Resource profile, CPU detection, model thread count,
trial/process concurrency and OS/architecture are execution metadata, so a compatible laptop run can resume under
the overnight profile. Incomplete units are retrained. Completed units are reused only when their unit identity
matches and any referenced artifact manifest passes SHA256 verification.

The run manifest records model families/targets, UTC lifecycle timestamps, Git commit and dirty flag, semantic
processed-data identity, input-manifest and processed-file content checksums, normalized configuration identity,
ML source identity, temporal boundaries and availability rules, seeds, effective resources, implementation
versions, metrics,
baselines, artifact locations/checksums, evaluation state and sanitized failure information. Scientific identity
fields are fixed when a run starts. `run.json` retains lifecycle and high-level summaries; checkpoint status,
parameters, metrics, evaluation state, execution reference and failures are stored one file per candidate/trial/fold
or forecast origin. Completed checkpoints and completed run manifests are immutable through the registry API.

`laptop` defaults to a conservative CPU and memory budget and one trial/process. `overnight` increases bounded
utilization.
Every profile enforces `model_threads × parallel_trials × process_concurrency <= cpu_budget`; unspecified model
threads are derived from the remaining budget, and oversubscribing explicit overrides are rejected. BLAS/OpenMP
limits are set before numerical libraries load. Every DuckDB feature session applies the derived thread limit and a
per-worker memory limit; `--duckdb-memory-mb` is rejected when aggregate workers would exceed the profile budget.

Python, NumPy and LightGBM seeds are centralized and recorded. Relevant Python/library versions participate in
scientific identity. Platform/architecture are recorded per execution and warn on cross-platform resume; the
contract does **not** promise bit-for-bit equality across platforms.

The forecast-origin convention is uniform: an origin is the last observed day, and horizon `1..h` predicts
`origin + 1` through `origin + h`. No warm-up exclusion is currently executed, so protocols record no warm-up
period. Only the coordinator writes run/checkpoint state; workers compute and return results. One local writer owns
a run via a fenced `.run.lock`; normal exits, exceptions and Ctrl+C release it. Hard-kill locks are never removed
automatically and require the exact observed ID after diagnosis:

```bash
make train ARGS="--recover-stale-lock <run-id> --confirm-lock-id <lock-id>"
```

Recovery refuses a live same-host owner. A remote/unknown owner also requires
`--force-remote-lock-recovery`, and successful recovery leaves an audit record.

Every new model directory has `artifact-manifest.json`, containing sorted per-file sizes/SHA256 values and one
aggregate content identity. Loading and PostgreSQL registry publication verify it first and fail on corruption.
Existing pre-6B.1 artifacts receive a checksum sidecar on first load and remain usable as explicitly
`legacy_unattributed`; only new artifacts with complete evaluation lineage can be registered as fully
attributed.

Evaluation completion makes a candidate eligible for review, not current. `--promote` validates all selected
artifacts and atomically replaces the complete filesystem current-set manifest. Prediction then mirrors that
verified selection and its nullable lineage into PostgreSQL in one database transaction. The filesystem selection
and database serving snapshot are deliberately retryable stores, not a distributed transaction.
