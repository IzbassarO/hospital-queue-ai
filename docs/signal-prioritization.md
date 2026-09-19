# Signals Inbox prioritization and explanation

This workflow converts an accepted preventive-flow-pressure run into concise machine-readable views
for future human-operator presentation. It reads immutable entity/origin pressure and observed-anomaly
artifacts only. It does not load daily-cell alerts, refit forecasts, change pressure severity, create a
capacity claim, or modify backend/frontend contracts.

## Canonical unit and targets

The canonical Inbox unit is one
`hospital/profile/target/origin` (`hospital_profile_target_origin`) row. The pressure source has already
consolidated daily horizons, so a warning persisting for 14 days remains one Inbox item. First crossing,
maximum severity within 7 and 14 days, and the exact horizon/date and numeric evidence explaining the
displayed maximum are preserved.

Only `registrations` enter the primary warning Inbox and unsupported data-quality queue.
`cohort_hospitalizations` are persisted separately as research evidence for the Q1 referral cohort;
they are not total admissions and do not enter the primary ranking.

## Fixed lexicographic ranking

`inbox_rank` is computed independently within phase/origin/target. There is no learned model, tuning,
weighted sum, or opaque score. Earlier items win on the first differing key:

1. severity: `HIGH`, then `ELEVATED`, then `WATCH`;
2. shorter first-crossing `lead_time_days`;
3. direct forecast with supported local history before fallback or limited history;
4. available calibrated uncertainty before unavailable uncertainty;
5. larger `forecast_value / threshold_value`, only when the supported threshold is finite and > 0;
6. ascending region, hospital, profile, and series identifiers as deterministic tie-breakers.

Observed-anomaly context is not a ranking key. `UNSUPPORTED` or threshold-unsupported rows are excluded
from the warning ranking and placed in `unsupported_data_quality` with their own stable data-quality
order. Normal rows do not become warning items.

The fixed product materiality floor is 1.0 expected count/day. When a supported historical threshold
is exactly zero and the central forecast is below that floor, the source severity and all source
numeric evidence remain unchanged, but `materiality_status` becomes `zero_baseline_low_volume` and
`operational_priority_status` sends the item to `zero_baseline_low_volume_attention`. It cannot enter
the primary ranking. This is untuned product triage for integer daily counts, not model calibration or
a claim that the source pressure signal is false. Zero-baseline forecasts at or above 1.0 and every
positive-threshold signal remain governed by the unchanged lexicographic ranking.

## Explanation contract

Every warning or data-quality row has deterministic `headline`, `concise_reason`, source `reason_codes`,
and `evidence_facts`. Text describes forecast/threshold evidence, support/fallback provenance, calibrated
uncertainty availability, and the displayed-severity evidence day. It never attributes a flow change to
a feature or makes a causal claim. Regional fallback is stated explicitly when local history is limited;
zero-history fallback does not fabricate uncertainty. Low-volume attention rows use a diagnostic
headline rather than presenting their preserved source `HIGH`/`ELEVATED`/`WATCH` label as primary
operational pressure.

`preventive_flow_pressure` remains a future signal. `observed_unusual_flow` remains a contemporaneous
observed anomaly. The boolean `observed_anomaly_present` adds context to a future warning but never
changes forecast-pressure severity.

## Views, roll-up, and artifacts

The ignored evaluation artifact contains `top_priority_all`, `high_only`, `watchlist_7d`,
`watchlist_14d`, `fallback_attention`, `unsupported_data_quality`,
`zero_baseline_low_volume_attention`, and `observed_anomalies` parquet views. It also contains secondary
cohort evidence, regional summaries, analysis metadata, and demos: top 20 eligible Inbox examples, a
HIGH direct-support example, regional-fallback example, anomaly-plus-warning example when available,
unsupported example, low-volume zero-baseline example, and regional summary examples.

Regional summaries are transparent counts of HIGH/ELEVATED/WATCH and unsupported entities, nearest
crossing lead time, top affected profiles, and direct-versus-fallback shares. They are not a regional
risk model. Signals require human review and cannot trigger rerouting, diagnosis, treatment, automatic
action, or model promotion.

```bash
make signal-prioritization PROFILE=laptop ARGS="--source-run flow-pressure-6b2c1-real-v2 --run-id signal-prioritization-6b2c2-real-v2"
```
