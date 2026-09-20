# Forecast Stress-Test Engine

## Status and purpose

Step 6B.3 is implemented as an offline Scenario Engine and is **CLOSED**: accepted on real data
(run `flow-scenario-6b3-real-v1`, verdict ACCEPT WITH P2 ONLY; see "Real-data acceptance" below).
It answers one restricted question:

> If registrations followed this explicitly specified synthetic scenario, how would the existing
> historical-flow warning system respond?

It does not answer what will happen if an operational or policy intervention is implemented. The
runtime mode is `EVALUATION`; accepted retrospective artifacts are not presented as live serving
predictions.

"Scenario outputs describe the response of the accepted forecasting and
historical-flow warning system to explicitly specified synthetic inputs. They
do not estimate causal effects of operational or policy interventions."

The name Digital Twin is not used because this implementation has no accepted physical-capacity
state, service mechanism, joint stochastic process, causal intervention response, or validated queue
trajectory. Calling it a twin would imply fidelity that the evidence does not establish.

## Accepted baseline and lineage

The reviewed configuration fixes this source chain:

```text
flow-hierarchy-6b2b3-real-v1
  → flow-pressure-6b2c1-real-v2
  → signal-prioritization-6b2c2-real-v2
```

The pipeline verifies completed immutable checkpoints and artifact hashes for the pressure and
prioritization sources, verifies their hierarchy/pressure links, and records source dataset,
configuration, code, scientific, checkpoint, and artifact identities. It also records the scenario
contract/config identity, full specification, source Git/code identity, and output artifact hash.
Scenario evidence never enters `ModelRegistry` and cannot promote a predictive model.

The primary input is the accepted hospital/profile registration central forecast with origin,
target date, horizon, support/fallback facts, threshold facts, and level-local calibrated-range
availability. `cohort_hospitalizations` is retained only as untouched secondary context and is
explicitly not scenario-adjusted.

## Executable levers

All perturbations execute on hospital/profile registration rows before parent aggregation.

- `identity`: no transformation; required reproduction gate.
- `demand_multiplier`: `scenario_central = multiplier × baseline_central`, with `multiplier >= 0`.
  Scope may be all hospitals, one hospital/profile, one region/profile, one profile, and a horizon
  window. Parent scopes allocate their aggregate change to hospital rows proportional to baseline
  central and are explicitly labelled `proportional_to_baseline_central_heuristic`. A non-identity
  request with all-zero eligible children fails instead of inventing allocation.
- `profile_surge`: the same deterministic multiplier constrained to region/profile/horizon scope.
  It is a synthetic demand stress, not a probability or policy claim.
- `inflow_transfer`: transfers fraction `phi` in `[0,1]` from hospital A/profile P to hospital
  B/the same profile for aligned dates. The affected profile/date total is conserved within `1e-9`.
  Metadata states `feasibility = UNKNOWN`, `capacity_checked = false`, and
  `causal_effect_claimed = false`.
- `time_shift`: shifts central values by whole days within the selected subset of the 1–14 horizon.
  A positive `days` is a delay and a negative `days` is an advance. The shift never wraps, never
  redistributes values crossing the boundary, and zero-fills vacated cells. Mass leaving the selected
  window is recorded as `edge_mass_lost`; `edge_mass_gained` is zero in v1. An absolute shift equal to
  or larger than the selected window length is rejected rather than silently zeroing the scenario.

  Time shifting changes synthetic central inflow only. Scenario sensitivity bounds are derived from
  each destination cell's baseline uncertainty using the destination-local central delta; uncertainty
  evidence is not moved between dates. Nothing is re-calibrated.

Only `SAFE_NON_CAUSAL_STRESS_TEST` and `MECHANISTIC_ACCOUNTING_SCENARIO` classifications execute.
Unknown levers and classifications requiring causal identification, missing capacity data, or other
unsupported science fail with machine-readable `LEVER_UNSUPPORTED` and a reason. Levers are never
silently ignored.

Exactly one reviewed lever executes per scenario. Ordered multi-lever `composite` specifications are
**not supported in v1** and fail with `COMPOSITE_NOT_SUPPORTED_V1`; sequential lever composition has
its own review requirements and is deliberately deferred. Contract violations raise machine-readable
codes, including `INVALID_MULTIPLIER`, `INVALID_TRANSFER_FRACTION`, `INVALID_TRANSFER_ALIGNMENT`,
`INVALID_SCOPE`, `INVALID_TIME_SHIFT`, `INVALID_LEVER_PARAMETERS`, and `ALLOCATION_WITHOUT_SUPPORT`.
Because Python treats `bool` as an integer, boolean multipliers and transfer fractions are rejected
explicitly rather than silently read as `1.0` or `0.0`.

## Explicitly unsupported

The engine does not implement:

- queue, backlog, or clearance-time forecasting;
- the queue accounting identity as a forecast trajectory;
- fluid queueing, discrete-event simulation, or stochastic service rates;
- Monte Carlo paths or joint predictive probabilities;
- latent capacity, occupancy, beds, or staffing effects;
- refusal intervention, causal rerouting, capacity optimization, or policy counterfactuals;
- response of cohort hospitalizations to registration shocks;
- a scenario benefit score;
- live legal-origin scoring or a serving claim.

`uncertainty_stress`, threshold-rule sensitivity, and ordered `composite` lever sequences are also not
executable in v1. They may be reviewed later as deterministic sensitivity rules, but an unsupported
request currently fails explicitly. In particular, the accepted pressure configuration is never
changed globally, and thresholds always remain the accepted factual historical reference.

## Scenario sensitivity range

Accepted calibrated uncertainty is level-local evidence. It is not a joint predictive distribution,
and the scenario output is not calibrated uncertainty. Raw p10/p50/p90 and accepted calibrated bounds
remain untouched.

For a hospital row with a usable accepted calibrated range, v1 applies
`additive_central_shift_v1`:

```text
delta_c = scenario_central - baseline_central
scenario_sensitivity_lower = max(0, baseline_lower + delta_c)
scenario_sensitivity_upper = max(scenario_sensitivity_lower, baseline_upper + delta_c)
```

The output label is `TRANSFORMED_BASELINE_UNCERTAINTY_RANGE`. Its semantics are **derived
sensitivity range, not re-calibrated, no coverage guarantee**. When accepted uncertainty is missing
or insufficient the scenario range status is `UNAVAILABLE`, and the cell also carries the reason code
`SCENARIO_SENSITIVITY_RANGE_UNAVAILABLE`. That code means the baseline forecast evidence lacks usable
uncertainty support, so the scenario cannot derive uncertainty-dependent synthetic WATCH or HIGH
evidence. It is not a model failure, not a capacity issue, and not a confidence score. Missing range
evidence cannot create WATCH or HIGH. Region and national rows contain central values only and use
`NOT_SCENARIO_ADJUSTED`; no parent interval is manufactured.

### Public field vocabulary

Scenario artifacts keep accepted evidence and derived sensitivity in separate, explicitly named
fields. The accepted calibrated names are never reused for transformed values.

| Accepted baseline evidence | Scenario derived sensitivity |
|---|---|
| `baseline_central` | `scenario_central` |
| `baseline_uncertainty_lower` / `baseline_uncertainty_upper` | `scenario_sensitivity_lower` / `scenario_sensitivity_upper` |
| `baseline_uncertainty_status` | `scenario_uncertainty_status` |
| `baseline_calibration_status` / `baseline_calibration_version` | `scenario_calibration_status` (always `baseline_only_not_scenario`) |
| `baseline_level_local_interval_80_lower` / `_upper` | `scenario_uncertainty_method` = `additive_central_shift_v1` |

The accepted pressure and prioritization functions are reused unchanged and internally require the
legacy working names `forecast_value`, `uncertainty_lower`, and `uncertainty_upper`. Those are
supplied through a private in-memory adapter frame and are stripped before publication, so they never
appear as public scenario semantics. A published scenario field is never described as calibrated, a
confidence interval, a prediction interval, an 80% interval, or a raw p10/p90 quantile.

## Hierarchy, pressure, and prioritization

Scenario region central equals the exact sum of hospital central, and national central equals the
exact sum of regions. This is central coherence, not probabilistic reconciliation.

The engine calls the existing pressure severity and entity aggregation functions. It preserves the
`historical_flow_proxy_v1` meaning and the states `UNSUPPORTED`, `NORMAL`, `WATCH`, `ELEVATED`, and
`HIGH`. Threshold, support, forecast-source, and fallback fields remain factual baseline provenance.
A transformed fallback forecast does not become directly supported.

It then calls the existing materiality and prioritization implementation. The fixed 1.0 expected
count/day floor is not tuned. Ranking stays fixed and lexicographic—severity, shorter lead time,
direct support, baseline calibrated-range availability, valid central/threshold ratio, and stable
IDs—with no score. Observed anomaly is copied as baseline context; it is never transformed and does
not modify pressure severity.

## Per-target summaries

Summaries are reported **per target** under an explicit `primary_target: registrations`. Cohort
hospitalizations are untouched context, so they never enter the registrations denominator; pooling
the two targets would have halved every measured registrations effect.

```text
primary_target: registrations
targets:
  registrations:
    daily_cells: total, severity_changed_count, severity_changed_share, transition_matrix, severity_counts
    entities:    total, severity_counts, changed_count, changed_share
    inbox:       baseline_size, scenario_size, entered, left, direct_supported,
                 fallback_limited, zero_baseline_low_volume_attention
  cohort_hospitalizations:
    scenario_adjustment: NONE
    semantic_role: UNCHANGED_SECONDARY_CONTEXT
    row_count, entity_count, severity_changed_count
```

## Retrospective evaluation labels

This is an `EVALUATION` run over accepted retrospective artifacts, so scenario outputs inherit
baseline evaluation labels: `phase`, `y`, `actual_exceeds_threshold`, `actual_event_within_7d`,
`actual_event_within_14d`, `evaluation_supported_7d`, and `evaluation_supported_14d`. These describe
observed history. They are **not scenario predictions**, carry no scenario meaning, and are not
serving-eligible. A future serving adapter must strip them, exactly as required by the 6B.2D serving
contract. The scenario metadata declares them under `retrospective_evaluation_labels` with
`serving_eligible = false`.

## Difference and validation outputs

Daily and entity differences include baseline/scenario central, absolute delta, nullable relative
delta when baseline is zero, baseline/scenario severity and threshold, severity-change status,
baseline/scenario Inbox ranks, and entered/left Inbox flags where applicable.

Before any nonzero scenario output is published, the mandatory identity gate compares accepted and
recomputed scientific fields as explicit `(scenario field, accepted field)` pairs, because scenario
artifacts deliberately publish scenario-scoped names:

- daily: `scenario_central` against accepted `forecast_value`, `scenario_sensitivity_lower/upper`
  against accepted `uncertainty_lower/upper`, `severity`, `threshold_value`, `threshold_status`, and
  the accepted `source_reason_code`;
- entity: `severity`, `max_severity_7d/14d`, `first_crossing_date`, `first_crossing_severity`,
  `lead_time_days`, `any_alert_7d/14d`, `severity_evidence_horizon`, `severity_evidence_date`,
  `scenario_central` against accepted `forecast_value`, `threshold_value`, the sensitivity bounds, and
  `source_reason_code`;
- Inbox, unsupported, and low-volume views: `source_severity`, `first_crossing_date`,
  `lead_time_days`, `materiality_status`, `operational_priority_status`, `priority_support_class`, and
  the deterministic rank.

Numeric comparisons use tolerance `1e-9`. Runtime timestamps are excluded. Other checks cover transfer
conservation, exact hierarchy coherence, scope invariance, edge mass, input immutability, unchanged
secondary target/raw quantiles/provenance/anomaly context, and deterministic scientific hashes.

Scenario scientific identity covers the scenario contract/config, the accepted source-run identities,
and the scenario specification. A specification's `created_at` is audit metadata only: an identical
scientific specification with a different timestamp produces an identical scientific identity.

A restricted historical replay may later feed realized **registrations** at each legal origin to
verify that threshold/severity machinery reacts as specified. It cannot validate policy effects,
intervention outcomes, causal benefit, or scenario predictive skill. This is not counterfactual
validation.

## Standard real-data evidence suite

The reviewed cases are fixed before outcome inspection and are not model candidates:

- baseline identity;
- national registrations ×0.90;
- national registrations ×1.10;
- national registrations ×1.20.

The reviewed stress levels are fixed in configuration, and the run fails fast if
`default_demand_stress_levels` and the standard demand-multiplier scenarios ever drift apart.

Each summary reports, **for registrations only**, changed daily cells and share, the severity
transition matrix, scenario severity counts, entity totals and changed share, baseline and scenario
primary Inbox sizes, entered/left counts, direct/fallback composition, and low-volume attention count,
plus hierarchy coherence, runtime, and peak memory. Cohort hospitalizations are reported separately as
unchanged secondary context. No case is selected as “best.” A representative transfer pair is
deliberately not chosen from final-test outcomes; transfer acceptance uses synthetic conservation
tests.

## Run and artifacts

Inspect the immutable plan without executing the suite:

```bash
make flow-scenario PROFILE=laptop ARGS="--plan"
```

The user-run real-data acceptance command is:

```bash
make flow-scenario PROFILE=laptop ARGS="--run-id flow-scenario-6b3-real-v1"
```

A reviewed single-spec JSON can be run with `--scenario-spec`. The baseline provenance in that spec
must exactly match the configured accepted chain.

Generated evidence is ignored by Git and atomically published under:

```text
artifacts/flow_scenario/<run-id>/
  evaluation/forecast-stress-test-<hash>/
    manifest.json
    config.json
    scenario-summary.json
    validation.json
    observed-anomaly-context.parquet
    scenarios/<scenario-id>/
      spec.json
      summary.json
      scenario-cells.parquet
      hierarchy-cells.parquet
      entity-signals.parquet
      inbox.parquet
      unsupported-data-quality.parquet
      zero-baseline-low-volume-attention.parquet
      secondary-context-not-scenario-adjusted.parquet
      daily-differences.parquet
      entity-differences.parquet
  summaries/scenario-summary-<hash>/
    summary.json
    validation.json
```

## Real-data acceptance

The standard suite was executed once on real data and reviewed independently, read-only:

- run id: `flow-scenario-6b3-real-v1`;
- implementation commit: `36e83f26b8d1e0c5e7a53ec74e102c9d24d4103f` (clean worktree, recorded in the
  evaluation manifest and experiment run record);
- scientific identity: `483dd631ce27d02e351db5b8b8f1e7ac0325bf789c9f35daf897560dbcf51098`;
- baseline reproduction: **PASS** at tolerance `1e-9` over 732,144 daily rows, 52,296 entity rows,
  7,253 Inbox rows, 4,081 low-volume rows, and 502 unsupported rows;
- acceptance verdict: **ACCEPT WITH P2 ONLY** (P0: none; P1: none).

Standard scenario results for `registrations`:

| scenario | daily severity changed (share) | entity changed (share) | Inbox | entered | left |
|---|---|---|---|---|---|
| baseline identity | 0 (0) | 0 (0) | 7,253 → 7,253 | 0 | 0 |
| ×0.90 | 6,320 (0.0173) | 1,085 (0.0415) | 7,253 → 6,409 | 0 | 844 |
| ×1.10 | 30,392 (0.0830) | 3,194 (0.1222) | 7,253 → 8,073 | 821 | 1 |
| ×1.20 | 37,695 (0.1030) | 4,360 (0.1667) | 7,253 → 8,845 | 1,593 | 1 |

In every scenario the region and national central sums are exact (error 0), source frames and raw
quantiles are unchanged, `cohort_hospitalizations` is unchanged, counterfactual validation is false,
the scenario range carries no coverage guarantee, nothing is promoted, no serving claim is made, and
human review is required. Runtime was 1,803.5 s with peak memory 3,562.6 MiB on the laptop profile.

The accepted capability is non-causal scenario stress testing. It is not a Digital Twin, causal
intervention model, patient-rerouting model, queue or backlog predictor, occupancy or bed/staffing
simulator, Monte Carlo joint simulation, or policy counterfactual validation.

## Interpretation limitations

These P2 caveats are non-blocking and are recorded for anyone reading the accepted artifacts.

1. **Inherited reason-code vocabulary.** Machine-facing `reason_codes` and `source_reason_code` may
   retain accepted source tokens such as `CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD` and
   `CALIBRATED_UPPER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD` even when severity was recomputed from
   scenario sensitivity bounds. Operator-facing text is rewritten to "Derived scenario sensitivity
   lower/upper bound", and the row metadata says `baseline_only_not_scenario` and
   `derived_sensitivity_range_not_recalibrated`. The inherited tokens are historical source
   vocabulary and must not be interpreted as evidence that scenario bounds were calibrated.
2. **Zero-threshold knife edge.** Under positive stress most ELEVATED→HIGH transitions occur on
   zero-threshold sparse cells where the baseline lower bound is exactly 0. For ×1.10, 23,608 of
   23,609 ELEVATED→HIGH daily transitions are such cells, so any positive central/range shift
   satisfies lower > 0. This is inherited from the accepted 6B.2C-1 severity rule. The product
   materiality rule keeps these cells out of the primary Inbox, so entity HIGH can rise strongly
   while operationally material primary-Inbox HIGH stays small. Do not reinterpret these transitions
   as physical overload.
3. **Monotonicity validator.** The built-in validator checks the sign of the central delta. The
   acceptance review independently recomputed severity transition direction and confirmed 0 upward
   transitions for ×0.90 and 0 downward pressure transitions for ×1.10 and ×1.20.
4. **Scope-invariance counts.** Changed-cell counts use tolerance `1e-9` and therefore differ from
   exact-arithmetic nonzero-change counts for near-zero rows. The meaningful invariant,
   `unexpected_changed_cells = 0`, passed.
5. **`deterministic_synthetic_inputs`.** This protocol flag means the scenario inputs and
   perturbations are explicitly deterministic synthetic stress specifications. It does not mean the
   underlying observed or forecast dataset is synthetic.
6. **Summary lineage.** The summary checkpoint does not independently repeat the Git commit.
   Clean-tree and code lineage are authoritative from the evaluation manifest and the experiment run
   record; the summary is linked to that evaluation by content hash.
7. **Memory.** Peak RSS was about 3,562.6 MiB, above the nominal 2 GiB laptop profile budget. This
   did not affect scientific correctness or run completion. Future performance work may reduce
   baseline entity/Inbox recomputation; it must not change scientific results.

Next ML stage: **6B.4 — Constrained Optimizer / Decision Alternatives**. It is not designed here.

Future evolution requires separate review and evidence for live legal-origin scoring, real
capacity/occupancy/staffing data, an accepted refusal-flow forecast, intervention identification,
longer history, and validated joint uncertainty.
