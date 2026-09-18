# Flow forecast evidence contract

This workflow evaluates daily operational counts for preventive overload warnings. It does not
estimate bed capacity, occupied beds, or free beds, and it does not publish a serving model.

## Targets and source limits

- `registrations` is the daily number of referral registrations: an operational inflow count.
- `hospitalizations` is the daily number of hospitalization events recorded for referrals in the
  Q1 referral extract. It is not a census of all admissions to a hospital.
- Early January cohort hospitalization history is left-censored and structurally incomplete because
  referrals registered before 2025-01-01 are absent. January counts are not steady-state total
  admission history.
- The dense aggregate calendar spans 2025-01-01 through 2025-03-31. The ingest process emits every
  date for every observed hospital/profile key, so a stored zero is an observed no-event day. A
  missing date or null is an integrity error and is never converted to zero.
- Ninety days cannot support a claim about annual seasonality. Weekly baselines are evaluated only
  because several weekly repetitions are present.

Hospital/profile counts roll up by the hospital's mapped region. Region/profile counts roll up to
national/profile counts. Forecasts remain operational event counts throughout this hierarchy.

## Evaluation protocol

All origins use last-observed-day semantics and predict horizons 1 through 14. Rolling validation
origins are 2025-02-16, 2025-02-23, and 2025-03-02. Their last target is 2025-03-16. The untouched
final origin is 2025-03-17, predicting 2025-03-18 through 2025-03-31. No final-test result selects a
candidate, feature, fallback, or parameter.

Five deliberately small baselines are evaluated: recent value, 7-day trailing mean, 28-day trailing
median, seasonal naive at lag 7, and the mean of up to four recent matching weekdays. The challenger
is the existing fixed Poisson LightGBM using the unchanged direct multi-horizon feature contract in
`hqai_ml.features.load`; this workflow performs no tuning.

Unsupported hospital/profile series fall back deterministically to their region/profile forecast
scaled by the origin-time historical share. Unsupported region/profile series similarly use the
national/profile parent. If a parent has no historical target volume, the series uses its own recent
seasonal history and is explicitly labelled `own_history_zero` or `own_history_seasonal`; it never
silently receives a global average or an unlabeled zero.

The current challenger directly models every region/profile series, matching existing Model C
support semantics. National/profile forecasts are exact sums of region/profile predictions; national
series are not inserted into the LightGBM training population. The broader parent ladder remains
deterministic for future short-history panels, while the present 90-day panel primarily exercises
hospital-to-region fallback. Hospital and region predictions are not reconciled in this task.

Reports include macro-series and volume-weighted MAE, WAPE, RMSSE where a nonzero one-step scale is
defined, and Poisson deviance. Hierarchy-level results are canonical: hospital, region, and national
rows are never pooled into an artificial overall metric. Reports also split by horizon, region,
density band, and fallback level. The recommendation compares the challenger with the strongest
baseline by validation WAPE for each target and level; final-test results never select it. Forecasts
above a configured ratio to the series' historical maximum are reported, with zero-support handling
and examples, but are not clipped. Raw per-origin evaluation rows and a machine-readable summary are checksummed under
`artifacts/flow_forecast/<run-id>/`. The experiment identity covers data, configuration, source code,
versions, seeds, and the temporal protocol. Each origin is independently checkpointed and reusable.

Run with `make flow-evidence PROFILE=laptop`; resume with
`make flow-evidence PROFILE=laptop ARGS="--resume <run-id>"`. Automatic promotion is disabled.
The model thread count follows the selected resource profile and is execution metadata, not scientific
identity. During development the LightGBM `left_count > 0` assertion was observed with both one and
four threads, so threading is not an established cause. The code change preceding the stable run
removed national/profile rows from LightGBM training and instead derived national forecasts as exact
region sums; this is evidence of sequence, not proof of root cause. Interrupted units use explicit
interrupt checkpoints, and artifact directories are published atomically from unique partial paths.

`data_rollups_exact` in the summary means that observed child counts aggregate exactly to their data
parents. It does not claim that hospital forecasts are reconciled or coherent with region forecasts.
