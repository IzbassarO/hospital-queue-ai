# Preventive flow-pressure and early-warning foundation

This workflow turns the accepted hospital-level coherent central forecast into evidence for human
review. It does not represent physical capacity: the available data contain no bed capacity,
occupied-bed, or free-bed measurements. Product-facing signals are therefore named **flow
pressure**, **high-load warning**, and **unusual-flow warning**, never physical-capacity overload.

The current versioned threshold interface is `historical_flow_proxy_v1`. A future real capacity feed
may implement `physical_capacity_provider_v1` through the same downstream fields. This preparation
does not implement, simulate, or estimate that provider.

## Origin-legal historical threshold

For each hospital/profile, target, forecast origin, and target-date class, the workflow computes one
fixed 90th-percentile empirical threshold using the `higher` order statistic. Only observations at or
before the forecast origin are eligible, within a 56-day window. Date classes are holiday, weekend,
and weekday using the existing reviewed calendar.

The deterministic fallback ladder is:

1. hospital/profile observations in the target date class;
2. hospital/profile observations pooled across date classes;
3. region/profile observations in the target date class;
4. region/profile observations pooled across date classes;
5. unsupported.

Date-class distributions require at least 6 observations and 2 positive-flow days. Pooled
distributions require at least 28 observations and 3 positive-flow days. Dense zero days remain real
observations, but zero history alone is not treated as supported threshold evidence. Threshold
source, sample count, positive-day count, history start/end, date class, and fallback level are
persisted. Ninety observed days do not support an annual-seasonality claim.

## Preventive severity and lead time

The rule is fixed before the real run:

- `NORMAL`: central forecast and every available calibrated interval bound remain at or below the
  historical-flow threshold;
- `WATCH`: the available calibrated upper bound strictly exceeds the threshold;
- `ELEVATED`: the coherent central forecast strictly exceeds the threshold;
- `HIGH`: the available calibrated lower bound strictly exceeds the threshold;
- `UNSUPPORTED`: an origin-legal historical threshold cannot be estimated.

The order is `NORMAL < WATCH < ELEVATED < HIGH`, so central/lower exceedances take precedence over
upper-only crossings. Calibrated intervals are used only when the accepted hierarchy artifact marks
them `level_local_calibrated`. Missing uncertainty cannot create WATCH or HIGH; a central exceedance
can still produce ELEVATED. These are deterministic high-flow proxy states, not overload
probabilities.

Daily evidence is also summarized by hospital/profile and origin with first crossing date, lead-time
days, maximum severity within 7 and 14 days, threshold, central forecast, available interval bounds,
and provenance. The entity/origin fields are `any_alert_7d`, `any_alert_14d`, `max_severity_7d`,
`max_severity_14d`, `first_crossing_date`, `lead_time_days`, `actual_event_within_7d`, and
`actual_event_within_14d`. The primary operational target is registrations.
`cohort_hospitalizations` remains separate Q1-referral-cohort evidence, not total admissions.

The entity `severity` is the maximum within 14 days. Its displayed forecast, threshold, interval,
reason, and provenance all come from the earliest target day attaining that maximum; the exact day
and horizon are recorded as `severity_evidence_date` and `severity_evidence_horizon`. First-crossing
date, lead time, and `first_crossing_severity` remain separately labelled and may describe an earlier,
less severe alert. Representative examples prefer registrations for the primary future-warning demo.

## Retrospective usefulness and observed anomalies

The retrospective proxy event is an observed count strictly exceeding the same origin-legal
historical threshold. The primary retrospective `alert_unit` is
`hospital_profile_target_origin_target_day`. Its precision, recall, and false-alert rate are
**daily-cell metrics**: a warning that persists through all 14 forecast days contributes 14 alert
cells. Median true-positive lead time is the median forecast horizon over true-positive daily alert
cells. These are not incident- or episode-level metrics.

A separately labelled companion view uses `alert_unit = hospital_profile_target_origin` and scores
each entity/origin once for each 7- or 14-day window. It reports any alert, maximum severity, any
observed proxy event, first crossing, lead time, precision, recall, and false-alert rate. A window is
eligible for these metrics only when all of its daily thresholds are supported. This aggregation is
also not an incident or episode definition. Validation and final-test reports remain separate, and
no rule or threshold method is selected on final-test evidence; there is only one precommitted
method.

The anomaly companion is a weekly-residual median/MAD detector for registrations observed at the
forecast origin. Its reference residuals end on the day before the origin. It reports unusual high or
low observed flow when the absolute robust z-score reaches 3.5 and otherwise reports normal or
unsupported. It makes no causal claim and is distinct from expected future pressure.

## Product and governance contract

Machine-readable rows include signal/type/severity IDs, hospital/region/profile IDs, origin, first
crossing and lead time, `threshold_status`, `threshold_fallback_level`, `max_severity_7d`,
`max_severity_14d`, forecast/threshold/interval values, threshold semantics, forecast/support/
fallback/uncertainty provenance, reason codes, data freshness, calibration version, and dataset,
forecast, and signal scientific identities. `signal_type = preventive_flow_pressure` identifies a
future warning; `signal_type = observed_unusual_flow` identifies a contemporaneous observed anomaly.
Severity wording does not erase that distinction. Representative examples are generated only under
the gitignored artifact hierarchy.

Signals cannot trigger autonomous action, patient rerouting, diagnosis, treatment recommendations,
or model promotion. Backend, OpenAPI, and frontend integration are outside this task.

```bash
make flow-pressure PROFILE=laptop ARGS="--source-run flow-hierarchy-6b2b3-real-v1 --run-id flow-pressure-6b2c1-real-v1"
```
