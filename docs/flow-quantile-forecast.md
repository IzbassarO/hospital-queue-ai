# Probabilistic flow forecast preparation

This workflow prepares p10, p50 and p90 forecasts for horizons 1 through 14 without promoting a
model. Its primary operational target is daily referral `registrations`. Its secondary research
target, `cohort_hospitalizations`, contains hospitalization events belonging to referrals registered
in the Q1 extract. It is not total admissions, occupancy, free beds, or physical capacity. Early
January cohort history is left-censored because referrals registered before 2025-01-01 are absent.

## Temporal and candidate contract

The protocol is identical to the accepted point-evidence run: rolling validation origins
2025-02-16, 2025-02-23 and 2025-03-02, followed by the untouched 2025-03-17 final-test origin. An
origin is the last observed date. No random split is permitted, and the final test cannot select or
calibrate a candidate.

The incumbent probabilistic baseline anchors p50 uncertainty to `recent_seasonal_average` and adds
horizon-specific empirical residual quantiles. A residual is eligible only when its target date is
at or before the forecast origin. The calibration method, window and identity are recorded
separately from model identity. With only 90 observed days, this is finite-sample empirical evidence,
not a claim of annual or asymptotic coverage.

The challenger fits three global LightGBM quantile objectives, alpha 0.10, 0.50 and 0.90, using the
existing direct multi-horizon features and categorical handling. It has one fixed configuration and
no broad HPO. Model threads follow the resource profile and remain execution metadata.

## Raw evidence and serving diagnostic repair

Raw quantiles are the primary scientific evidence and the only validation metrics permitted to govern
candidate retention. They expose negative outputs, crossing and extrapolation without silently sorting
or clipping them. Final-test metrics never govern retention. The separate
`repaired_nonnegative_monotone` serving/UI diagnostic applies `max(0)` followed by a cumulative
maximum across p10, p50 and p90. Its metrics remain reportable but cannot select a candidate.
Presentation examples use only this explicit repaired variant.

Metrics include pinball loss at each quantile, mean pinball loss, WIS for the central 80% interval,
empirical coverage, interval width, p50 MAE/WAPE/RMSSE, crossing rate and negative-output rate.
Hospital/profile, region/profile and national/profile metrics are canonical and never pooled.
Horizon, density/support and fallback views remain separate.

Unsupported hospitals inherit each parent region quantile through the existing origin-time historical
share. Zero-parent cases retain the explicit deterministic own-history fallback. When it produces
p10=p50=p90, zero interval width means no estimated uncertainty support—not certainty about the
future. Every row distinguishes statistical-residual baseline, direct quantile ML, and fallback source.

National values are labelled `region_quantile_sum_proxy`: each is the sum of corresponding region
quantiles. They are not mathematically valid national quantiles in general, are not probabilistically
reconciled, and do not establish national coherence. National proxy coverage and WIS describe only
the proxy interval, not a reconciled national predictive distribution. Sophisticated probabilistic
reconciliation remains deferred; the next hierarchy step reconciles only the central operational
forecast and leaves all interval evidence level-local.

For every quantile, candidate and raw/repaired variant, artifacts report prediction-to-historical-max
ratios, positive predictions with zero historical support, flagged cells/series and worst examples.
The threshold is report-only; forecasts are never clipped to it.

## Governance and local execution

`make flow-quantile PROFILE=laptop ARGS="--plan"` is read-only. The real run is independently
checkpointed by origin, atomically publishes artifacts under `artifacts/flow_quantile/<run-id>/`, and
can resume with `--resume <run-id>`. Its summary also writes three machine-readable examples: a
directly supported hospital/profile, an explicit sparse fallback, and a region/profile aggregate.
Automatic promotion is forbidden; validation reports mean pinball and WIS separately, with no
weighted score.

Repository-local ERSB data is a static organization-level snapshot with no treatment-period column
and no profile dimension. Its `sdu_load_date` is ingestion freshness, not a treated-case date. It has
hospital identifiers where matching succeeded, but it is not added to this training workflow and
cannot supply temporal treated-case labels for quantile calibration.
