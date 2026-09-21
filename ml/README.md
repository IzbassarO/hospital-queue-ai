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
    tournament/   censored journey labels, survival/competing-risk candidates and assurance metrics
    serving/      serving marts for the API (SQL run inside Postgres; docs/api.md)
  pipelines/
    ingest.py     make ingest
    baseline.py   make baseline → reports/01_baseline.md
    train.py      make train    → artifacts/models/, reports/02_models.md  (--model to run one)
    tournament.py make tournament → ignored candidate/checkpoint/decision artifacts; never promotes
    flow_hierarchy.py central-only hierarchy/fallback evidence from immutable forecast artifacts
    flow_pressure.py  historical-flow pressure/warning evidence from accepted hierarchy artifacts
    signal_prioritization.py deterministic entity/origin Signals Inbox from accepted pressure artifacts
    flow_scenario.py deterministic offline registration forecast stress tests from the accepted chain
    decision_alternatives.py exact retrospective constrained alternatives with mandatory full-engine verification
    predict.py    make predict  → pred_referral, pred_daily_forecast, model_registry (then build_marts.py)
    build_marts.py make marts   → mart_hospital_profile_status, mart_region_profile_status, mart_area_status
  configs/
    serving.yaml  as-of date, windows, load_index weights, status / alert thresholds, recommendation rule
    ingest.yaml   pipeline parameters (window, date ranges, thresholds)
    regions.yaml  region code dictionary — generated, reviewed by hand
    org_matches.yaml       manual hospital ↔ ERSB match overrides
    models.yaml            split, LightGBM defaults, forecast settings, holidays
    tournament.yaml        reviewed journey candidates, folds, search spaces, horizons and eligibility policy
    explain_templates.yaml Russian sentence templates for explanations
    signal_prioritization.yaml reviewed lexicographic Inbox ranking and governance contract
    flow_scenario.yaml reviewed scenario contract, accepted lineage, and standard sensitivity cases
    decision_alternatives.yaml precommitted donor cohort, policy-budget ladder, and verification bound
```

Pipelines are run with `PYTHONPATH=ml` (the Makefile sets it).

## Flow-forecast evidence

The non-promoting 1..14-day flow-forecast evidence workflow is:

```bash
make flow-evidence PROFILE=laptop
make flow-evidence PROFILE=laptop ARGS="--resume <run-id>"
```

It writes checksummed rolling-origin/final-test evidence under `artifacts/flow_forecast/` and never
changes the current model registry. See `docs/flow-forecast-evidence.md` for target and fallback
semantics.

The central hierarchy/fallback workflow consumes completed quantile and temporal-calibration runs,
evaluates three transparent central-only hierarchy contracts and one fallback challenger using
validation evidence, and writes only ignored artifacts. It never reconciles quantiles or promotes a
model. See `docs/flow-hierarchy-forecast.md`.

The preventive warning workflow consumes the accepted hierarchy artifact and builds origin-legal
historical-flow thresholds, deterministic future pressure states, and a robust observed-flow anomaly
companion. It does not infer physical bed capacity or take autonomous action. See
`docs/flow-pressure-warning.md`.

The Signals Inbox workflow consumes accepted entity/origin pressure artifacts, ranks registration
warnings with a fixed lexicographic contract, separates unsupported data-quality items and cohort
research evidence, and emits deterministic non-causal explanations and regional counts. Supported
zero-baseline signals below the fixed 1.0 expected count/day product floor remain source evidence but
move to a separate low-volume attention view. The workflow neither loads daily alert cells nor creates
a learned priority score. See `docs/signal-prioritization.md`.

The Forecast Stress-Test Engine consumes the accepted hierarchy, pressure, and prioritization chain.
It applies deterministic synthetic registration multipliers, scoped profile surges, same-profile
inflow transfers, and bounded time shifts at hospital/profile level; then it reuses the accepted
pressure and fixed lexicographic prioritization rules. It runs in retrospective `EVALUATION` mode and
publishes only ignored evidence artifacts. It does not forecast a queue, model capacity, simulate a
joint distribution, or estimate causal intervention effects. See `docs/flow-scenario-engine.md`.

```bash
make flow-scenario PROFILE=laptop ARGS="--plan"
make flow-scenario PROFILE=laptop ARGS="--run-id flow-scenario-6b3-real-v1"
make flow-scenario PROFILE=laptop ARGS="--scenario-spec /absolute/path/to/reviewed-spec.json --run-id <run-id>"
```

The Constrained Decision Alternatives Engine is an offline `EVALUATION` layer over the unchanged accepted
`inflow_transfer` lever. It computes the algebraic minimum transfer fraction, certifies the binary64 representation
upward, applies receiver no-worse breakpoints, Pareto-filters within evidence strata, and publishes only candidates
reproduced by the full Forecast Stress-Test Engine. Its policy budgets are not physical capacity values; all outputs
require human review and keep physical feasibility unknown. Inspect the precommitted plan with:

```bash
make decision-alternatives PROFILE=laptop ARGS="--plan"
```

No real-data 6B.4 acceptance run has been performed. See `docs/decision-alternatives-implementation.md`.

## Patient-journey tournament

`make tournament` models the distribution of time from referral registration to a terminal queue outcome instead
of treating observed hospitalizations as the complete population. Dataset-1 `hospitalization_dt` and `refusal_dt`
are the only terminal events: its documented `resolution_date` removes the referral from the queue. The source has
no separate status dictionary or refusal-reason field, and dataset 3 cannot be linked as a referral outcome, so no
other events are invented.

The retrospective label cutoff is fixed at `2026-05-13T00:00:00`, after the last recorded event on 12 May and before
the common source-load timestamp later on 13 May. Thus Q1 2025 registrations have outcome follow-up through 13 May
2026; open referrals are right-censored there. The principal cohort excludes 45 terminal events on a genuinely
earlier calendar date plus the one row carrying both terminal timestamps. It retains 104,598 same-calendar-date
events whose source time precedes registration time and assigns them modelling duration 0.5 days. A separately
reported strict timestamp-order sensitivity cohort excludes those records (662,486 eligible versus 767,084 in the
principal cohort). Hospital/profile/purpose exclusion shares are persisted. Repeated referral codes remain separate,
flagged observations.

The reviewed candidates in `configs/tournament.yaml` are a sort/cumulative-count Aalen–Johansen empirical baseline
with hospital/profile fallback, the unchanged legacy wait regression, XGBoost AFT with genuine infinite upper
bounds for censored rows, a LightGBM discrete hospitalization hazard, and a coherent multinomial discrete competing
risk model. The interval grid has nine bounded rows per referral and exact 7/14/30-day edges. XGBoost is the only new
dependency; it supplies the required native AFT likelihood and predicts only through its early-stopped best tree.
Native categorical features are used by XGBoost/LightGBM; the logistic refusal probe uses train-only frequency
encoding. Bounded scrambled-Sobol trials reuse the existing trial/fold checkpoints, so a second HPO framework is
unnecessary.

Splits are chronological and disjoint: training, HPO validation, calibration, then test. Calibrator fitting and
method selection use earlier/later halves of the calibration period; test labels are not accepted by the HPO API.
Each trial is scored on every compatible fold and one parameter set is selected by mean fold-validation objective.
Hospitalization candidates minimize mean Brier@7/14/30; competing-risk candidates minimize mean three-state
Brier@7/14/30. No probability is reused at an un-emitted time. Naive Brier/concordance evaluation fails if an
administrative censor enters the evaluated horizon. Outputs include horizon Brier scores, machine-readable
reproducible sigmoid coefficients/isotonic breakpoints,
cause-specific incidence, exact coherence checks, and region/profile/support assurance. Refusal benchmarks include
prevalence, regularized logistic, a fold-trained LightGBM selected only on validation, its uncalibrated/Platt/isotonic
versions. Legacy wait/refusal artifacts trained through 28 February 2025 are excluded whenever validation,
calibration or test overlaps that window. A deployment-realistic sensitivity refits with labels available only at
each test start and reports uncalibrated test metrics separately.

```bash
make tournament PROFILE=smoke
make tournament PROFILE=laptop
make tournament PROFILE=overnight
make tournament PROFILE=smoke ARGS="--resume <run-id>"
```

Smoke uses 4,000 rows, one fold/trial, one CPU slot and 512 MiB DuckDB memory. Laptop uses at most 80,000 rows, two
folds and eight trials per tree candidate. Overnight is bounded at 200,000 rows, two folds and 32 trials per tree
candidate, with nine CPU slots total and 4 GiB aggregate memory on the 16 GiB reference host. These are portable
detected resource limits, not hardware-specific logic.

Candidate files, calibration data, summaries and `champion-decision.json` live under ignored
`artifacts/tournaments/<run-id>/`. Tree gain is reported only as an operational association with higher/lower
near-term event probability, never a causal effect. Completion never calls `set_current`; the decision artifact
defaults to `no_promotion` unless a human review later finds a challenger clearly superior.

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

The probabilistic flow preparation is a separate non-promoting workflow. Inspect its immutable plan with
`make flow-quantile PROFILE=laptop ARGS="--plan"`; run it locally with an explicit run ID and resume the same ID if
interrupted. It emits raw and explicitly repaired p10/p50/p90 evidence for `registrations` and
`cohort_hospitalizations`. The latter is the Q1 referral cohort outcome, never total admissions or capacity. See
`docs/flow-quantile-forecast.md` for its temporal, calibration, fallback and hierarchy contract.

Temporal 80% interval calibration is prepared as a separate artifact-consuming workflow. It validates and reads a
completed flow-quantile run without retraining forecast models, preserves raw quantiles, and writes independently
versioned interval bounds. Run it only after its source run completes; see `docs/flow-temporal-calibration.md`.

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
