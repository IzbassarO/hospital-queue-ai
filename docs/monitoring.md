# Monitoring plan

What an operator watches once the system runs on a live feed, with the baseline measured on the published
retrospective origin 2025-03-17 and the source column every metric comes from. The model passport
([model-assurance-6b5.md](model-assurance-6b5.md)) lists monitoring as a future expectation and deliberately does
not invent alert thresholds; this document turns that expectation into metrics that the already published tables
support, with the first thresholds proposed for review at the start of a pilot.

Nothing here changes a model, a published value or the assurance bundle. Every metric is a query over
`operational_signal`, `operational_forecast`, `specialist_decision` or `access_log`.

## 1. Baseline on the published origin

Measured on 2026-09-27 against the active publication
`operational-intelligence-slice5-final-test-2025-03-17-v1` (4 194 signals, 225 680 forecast rows).

| Metric | Baseline | Where it comes from |
|---|---|---|
| Direct-supported signals | 50.5 % (2 118 of 4 194) | `operational_signal.support_status` |
| Fallback-limited signals | 49.0 % (2 057) | same |
| Unsupported signals | 0.5 % (19) | same |
| Direct-supported forecast rows (registrations) | 42.3 % (47 782 of 112 840) | `operational_forecast.support_status` |
| Calibrated forecast rows | 98.6 % | `operational_forecast.calibration_status` |
| Signals with calibrated uncertainty | 87.6 % (3 674) | `operational_signal.uncertainty_status` |
| Primary inbox after the materiality floor | 63.0 % (2 642) | `materiality_status = materiality_rule_not_triggered` |
| Zero-baseline low-volume attention | 25.0 % (1 047) | `materiality_status = zero_baseline_low_volume` |
| Observed unusual-flow signals | 12.0 % (505) | `signal_type = observed_unusual_flow` |
| Severity mix | WATCH 58.4 %, HIGH 20.6 %, ELEVATED 18.1 %, UNSUPPORTED 2.9 % | `operational_signal.severity` |
| Calibrated interval coverage, validation | 83 % against a nominal 80 % | accepted run `flow-calibration-6b2b2b-real-v1` |
| Calibrated interval coverage, final test | 70 % (weekday 75.1 %, holiday 66.7 %, weekend 59.7 %) | same |
| Warning recall over 14 days | 0.68 (7 days: 0.66) | accepted run `flow-pressure-6b2c1-real-v2` |
| Warning precision, hospital level, 14 days | 0.39 | same |

The two coverage rows are the reason this section exists: a live system that silently drifts below the
retrospective numbers would still look healthy on screen.

## 2. Metrics to compute per origin

Each row is one number per published origin. The first four are computable the moment a publication lands; the
last three need outcomes, so they lag by the horizon.

| # | Metric | Formula | Proposed first rule |
|---|---|---|---|
| 1 | Data freshness | `current_origin` of the active snapshot vs. today | alert when the newest origin is older than the agreed refresh SLA; today the state is `UNKNOWN` because no SLA exists |
| 2 | Fallback share | `count(support_status='FALLBACK_LIMITED') / count(*)` over `operational_signal` | review above 60 % (baseline 49 %): the feed is losing series history |
| 3 | Unsupported share | `count(support_status='UNSUPPORTED') / count(*)` | review above 3 % (baseline 0.5 %) |
| 4 | Inbox volume | `count(*) where materiality_status='materiality_rule_not_triggered'` | review when it moves by more than a factor of two between consecutive origins (baseline 2 642 over all origins, 598 on the final-test origin) |
| 5 | Schema and identifier drift | new `org_code` / `profile_code` values absent from `dim_organization` / `dim_profile`; rows failing the ingest data-quality gateway | any hard-gate failure stops the publication, as the gateway already does |
| 6 | Calibrated interval coverage | share of observed daily counts inside `[uncertainty_lower, uncertainty_upper]` over the last four completed origins | review below 0.65 (retrospective final test 0.70, validation 0.83) |
| 7 | Warning recall and precision | exceedances of the published threshold that carried a prior signal / signals followed by an exceedance, over completed 14-day windows | review when recall drops below 0.55 (baseline 0.68) or precision below 0.25 (baseline 0.39) |

Metrics 6 and 7 are the same computations the accepted evidence runs already perform
([flow-temporal-calibration.md](flow-temporal-calibration.md), [flow-pressure-warning.md](flow-pressure-warning.md));
in production they run over the live origins instead of the retrospective ones.

## 3. Human-side metrics

These say whether the human-in-the-loop part is alive, and they are the pilot's own success criteria. All of them
come from `specialist_decision`.

| Metric | Formula | Why it matters |
|---|---|---|
| Share of signals with a recorded decision | decisions / signals raised in the same period | a falling share means the inbox is being ignored |
| Time to decision | `created_at` minus the publication time of the signal | the operational value of a 14-day lead disappears if a signal waits a week |
| Share of declined signals | `count(action='decline') / count(*)` | a zero share is a warning sign: people are accepting without reading |
| Share of "request data" | `count(action='clarify') / count(*)` | points at the data gaps a pilot must close |
| Decisions without a comment | `count(comment is null) / count(*)` | an accountability record with no reason is weak evidence |

## 4. Operational metrics

`access_log` already holds one row per API request with the endpoint, status, latency and key label. Useful
without any new table: error rate by endpoint, p95 latency (the budget is a 500 ms test guard, current worst case
under 70 ms), request volume per key, and unauthorised attempts (401/403 by source). Publication events are
visible as new snapshot rows with their identity hashes.

## 5. What is deliberately not claimed

There is no live monitor running today: the system publishes one retrospective origin, so metrics 1, 6 and 7 have
nothing to accumulate over. The thresholds above are proposals for the first weeks of a pilot, not validated
control limits — with three months of data and one origin, a threshold chosen now would be guesswork dressed as
governance. What exists is the measured baseline, the query for every metric, and the tables that already carry
the columns.
