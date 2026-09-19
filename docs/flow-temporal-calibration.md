# Temporal uncertainty calibration

This is a separate, versioned calibration layer over saved raw Flow Forecast quantiles. It does not
retrain Quantile LightGBM, modify `raw_p10/raw_p50/raw_p90`, promote a model, or change the accepted
forecast origins. Calibrated outputs are named `calibrated_interval_80_lower` and
`calibrated_interval_80_upper`; they are not relabelled p10/p90 estimates.

## Methods and temporal legality

The primary method computes the non-negative conformity score
`max(raw_p10 - y, y - raw_p90, 0)` and symmetrically expands the raw interval by its finite-sample
80th-percentile score. The simple reference method uses `abs(y - raw_p50)` and forms an interval
around raw p50. The calibrated lower bound is explicitly truncated at zero because the targets are
operational counts: `max(0, proposed_lower)` affects only the calibrated lower bound. The calibrated
upper bound is then repaired as `max(calibrated_lower, proposed_upper)` so it cannot be below the
calibrated lower bound. Both repairs affect only calibrated interval outputs; raw p10/p50/p90 remain
unchanged.

For an origin O, scores may come only from validation forecasts with forecast origin before O and
target date at or before O. Thus final-test outcomes never calibrate themselves or select parameters.
The first validation origin can legitimately be unsupported because no earlier origin evidence is
available. The report shows nominal coverage 0.80, empirical coverage, sample counts and sharpness;
it does not hard-code an acceptance decision or claim exact 80% coverage.

## Support and date-class fallback

Calibration distributions remain separate for `direct_quantile_ml` and
`region_profile_share_fallback`. `own_history_zero` and other deterministic own-history fallbacks are
reported as `unsupported_own_history_no_uncertainty`; no interval is fabricated and zero width is not
treated as certainty. National `region_quantile_sum_proxy` rows are reported as unsupported for
national calibration claims because they are not a national predictive distribution.

Target dates are classified from existing calendar semantics as holiday, weekend, or weekday. Each
calibration class must meet both the configured score count and unique-target-date thresholds. The
deterministic fallback ladder is:

1. support class + horizon + date class;
2. support class + horizon, pooling date classes;
3. support class + date class, pooling horizons;
4. support class, pooling horizons and date classes.

Target and hierarchy level are never pooled by this ladder. If every rung is insufficient, bounds
remain null with `insufficient_calibration_support`. No causal interpretation is attached to date
class differences.

## Metrics and lineage

Canonical results are separate for hospital/profile and region/profile. Reports include empirical
coverage, gap from 0.80, interval width, interval score, a WIS-compatible score, outcome count,
unique target dates, calibration support counts, horizon, support class, date class, and direct versus
fallback views. National proxy metrics cannot be used to claim calibrated national coverage.

The runner requires a completed source run and compares its saved scientific protocol with a current
source plan component by component. Dataset and configuration identities, targets, origins/horizons,
quantile settings and hyperparameters, seeds, model contracts, and implementation versions must
match. Source and current code identities are both recorded for audit but are deliberately excluded
from equality: adding calibration code does not mutate the immutable source forecast artifacts.
Every origin checkpoint, origin/phase metadata value, and artifact checksum is still verified before
saved raw prediction rows are read; source models are never retrained. The original source run,
scientific, code, dataset, configuration/protocol, and artifact identities become calibration
lineage. Calibration version is separate from model version. Calibration checkpoints and summaries publish atomically under
`artifacts/flow_calibration/<run-id>/` and support resume.
