# Central flow hierarchy and fallback hardening

This non-promoting workflow evaluates an operationally coherent **central forecast** across
hospital/profile, region/profile, and national/profile levels. It consumes the immutable accepted
quantile and temporal-calibration artifacts; it does not fit a forecast model, modify source
predictions, infer bed capacity, or update serving systems.

## Evidence and temporal protocol

The accepted origins remain 2025-02-16, 2025-02-23, and 2025-03-02 for rolling validation and
2025-03-17 for untouched final testing, with daily horizons 1 through 14. Fallback selection and
hierarchy-method selection use validation registrations only. The final test is scored only after
both choices are frozen. No hierarchy level is pooled into another level's accuracy metric.

The central operational input is the already-defined `repaired_nonnegative_monotone` p50 serving
diagnostic. The source raw p10/p50/p90 values are retained under explicit `raw_*` names as unchanged
model evidence. Reconciled central values are written only as `forecast_value` and are labelled with
their source and hierarchy status.

## Two-stage transparent evaluation

The fallback stage compares the current `region_profile_share` fallback with one deterministic
`support_weighted_parent_own_blend`. The blend combines the current parent-share value with the
hospital's origin-legal recent seasonal average. Its own-history weight rises with observed non-zero
history days and is capped at 0.50. A zero-history series receives zero own weight and is never given
fabricated history. Validation WAPE, then macro-series MAE, then macro-series RMSSE on affected
hospital registration rows select the fallback contract; exact ties retain the incumbent.

The hierarchy stage evaluates only three central alternatives on the validation-selected fallback
base:

1. `current_direct`: unchanged hierarchy values;
2. `bottom_up_hospital`: region values are hospital sums and national values are region sums;
3. `parent_consistent_region_scaling`: hospital values are scaled to the accepted region/profile
   central value and national values are exact region sums.

A hierarchy alternative is eligible only when both hospital-to-region and region-to-national errors
are within the configured tolerance across validation cells. Eligible alternatives are ordered by
validation registration WAPE at hospital, region, and national levels, followed by hospital
macro-series MAE and RMSSE. Reports retain per-level metrics, both coherence boundaries, and the
count/share of materially changed child forecasts. Final-test results never alter the choice.

Parent scaling sends all child values to zero when a parent central value is zero. When children sum
to zero but a positive parent must be allocated, saved origin-time history totals provide the
weights. The allocation fails rather than distributing a positive parent across children with no
historical support. That parent-scaling alternative is recorded as ineligible; the other transparent
alternatives remain evaluable.

## Uncertainty and presentation semantics

This workflow performs no probabilistic reconciliation. Existing calibrated intervals remain
unchanged level-local evidence. If the central value is hierarchy/fallback adjusted, the row states
`level_local_calibrated_not_reconciled`; it does not move the interval or call it a distribution for
the adjusted forecast. National region-quantile sums remain historical diagnostic proxies and are
never labelled national quantiles. No coherent presentation interval is created.

Each selected row supplies `forecast_value`, `forecast_source`, `hierarchy_status`, `support_status`,
`fallback_status`, `uncertainty_status`, and `calibration_version`. These support future labels such
as Direct forecast, Regional fallback, Limited history, Uncertainty unavailable, and Hierarchy
adjusted without requiring backend or frontend changes in this step.

The evidence remains limited to 90 registration-history days, so it makes no annual-seasonality
claim. `cohort_hospitalizations` are events belonging to Q1-registered referrals, not total
admissions. Nothing in this workflow estimates beds, occupancy, free beds, or physical capacity.

## Local execution

Artifacts publish atomically under `artifacts/flow_hierarchy/<run-id>/` with source checksums,
checkpoint compatibility, validation-only selections, resource use, and resume support. Generated
outputs are gitignored. Automatic promotion is disabled.

```bash
make flow-hierarchy PROFILE=laptop ARGS="--source-run flow-quantile-6b2b2-real-v1 --calibration-run flow-calibration-6b2b2b-real-v1 --run-id flow-hierarchy-6b2b3-real-v1"
```
