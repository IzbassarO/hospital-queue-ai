# 6B.2D intelligence serving contract

Status: **ACCEPTED / CLOSED**  
Accepted: **2026-09-19**  
Contract version: `6b2d-accepted-v1`  
Scope: normative semantics only; no database, backend, OpenAPI, or frontend implementation exists for this contract.

Acceptance basis: independent adversarial review, the corrective specification pass, and final targeted re-review
with verdict **PASS WITH P2 ONLY**; all P0/P1 findings are resolved and scientific invariants A–M pass. 6B.2D
closes the semantic serving-contract design only. Persistence/API/frontend serving integration and legal-origin
runtime scoring remain future implementation work.

This document defines the candidate-independent semantic boundary between the accepted intelligence artifacts and
future persistence, HTTP, and UI adapters. The accepted evidence chain is:

`flow-evidence-6b2b1-corrected-v3`
→ `flow-quantile-6b2b2-real-v1`
→ `flow-calibration-6b2b2b-real-v1`
→ `flow-hierarchy-6b2b3-real-v1`
→ `flow-pressure-6b2c1-real-v2`
→ `signal-prioritization-6b2c2-real-v2`.

Patient Journey 6B.2A is also an accepted input. Neither a Patient Journey champion nor automatic promotion is
declared here.

## 1. Normative language and scope

`MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative. This contract owns statistical and product meaning, not
artifact storage shapes. An adapter MAY rename an artifact field only through an explicit, tested mapping and MUST
not strengthen its meaning.

The contract covers these future read models:

- `PatientJourneyAssessment`;
- `FlowForecastSeries` and `FlowForecastPoint`;
- `PressureSignal`;
- `ObservedAnomaly`;
- `SignalInboxItem`.

It does not define write commands, physical tables, endpoints, UI behavior, automatic actions, patient routing,
diagnosis, treatment, a Digital Twin, or an optimizer. Model-family names, training parameters, evaluation folds,
and outcome labels are not public serving semantics.

## 2. Canonical grains

| Read model | Canonical identity/grain |
|---|---|
| `PatientJourneyAssessment` | referral × `estimand_id` × prediction origin |
| `FlowForecastPoint` | entity × target × origin date × target date |
| `FlowForecastSeries` | entity × target × origin date, containing unique horizon 1–14 points |
| `PressureSignal` | hospital/profile × target × origin date; daily cells are evidence, not identities |
| `ObservedAnomaly` | hospital/profile × target × observation date |
| `SignalInboxItem` | one preventive pressure signal × ranking partition `(origin_date, target)` |

An identifier MUST be deterministic within its declared `id_scheme`. Current artifact identifiers are internal and
derived; they are not confirmed government source identifiers.

## 3. Shared value objects

### 3.1 `EntityRef`

| Field | Type / availability | Semantics |
|---|---|---|
| `level` | required enum | `HOSPITAL`, `REGION`, or `NATIONAL` |
| `series_id` | required string | Internal series identifier in `id_scheme`; not a source-system claim |
| `id_scheme` | required string | Current value is explicitly `internal_derived_v1` |
| `organization_id` | nullable string | Required only for `HOSPITAL`; current source is `org_code` |
| `region_id` | nullable string | Required for hospital and region levels; null for national |
| `profile_id` | required string | Orthogonal profile dimension; every current accepted series is profile-specific |

`organization_id` and `series_id` MUST NOT be described as stable government identifiers until the customer names
their source of truth and stability guarantees. An organization's current `region_id` comes from the derived
`dim_organization.region_code`: dataset-3 admission-refusal region where matched, otherwise the majority referral
origin prefix. It is not the patient origin-region segment in `hospitalization_code`.

### 3.2 `ReferralRef`

| Field | Type / availability | Semantics |
|---|---|---|
| `referral_id` | required string | Current candidate is the refresh-sensitive `row_number()` surrogate from `fact_referral` |
| `hospitalization_code` | nullable string | Source code retained for traceability; duplicates exist, so it is not an identity by itself |
| `id_scheme` | required string | Current value is explicitly provisional `internal_derived_v1` |

Neither `referral_id` nor `hospitalization_code` is confirmed as a stable production government identifier. A data
refresh can renumber the surrogate when ordered source rows change, and `hospitalization_code` is not guaranteed
unique.

### 3.3 `Provenance`

| Field | Type / availability | Semantics |
|---|---|---|
| `contract_version` | required string | Semantic contract version, independent of candidate implementation |
| `run_id` | required string | Immutable producing run identifier |
| `scientific_identity` | nullable string | Required when the source artifact supplies it; never fabricated |
| `dataset_identity` | nullable string | Required when supplied by lineage |
| `config_identity` | nullable string | Required when supplied by lineage |
| `code_identity` | nullable SHA256 | Producing scientific source-tree SHA256 (`code.source.sha256`), not adapter code identity |
| `git_commit` | nullable string | Producing repository commit; assurance metadata, not scientific code identity |
| `dirty_worktree` | nullable boolean | Producing-worktree assurance metadata; not scientific code identity |
| `artifact_identity` | nullable SHA256 | Verified published artifact content SHA256 |
| `model_version` | nullable string | ModelRegistry-style artifact/version reference when a model owns the prediction |
| `upstream` | required list of references | Ordered source-run IDs and available identities/checksums |

Null means that historical provenance is unavailable, not that it is irrelevant or verified. Candidate/model-family
names MAY appear in restricted assurance metadata, but MUST NOT alter the public field semantics or schema.
`code_identity`, `git_commit`, `dirty_worktree`, `artifact_identity`, and `model_version` are complementary concepts,
not aliases.

### 3.4 `Freshness`

| Field | Type / availability | Semantics |
|---|---|---|
| `origin_date` | required date | Last observation date available to the forecast/assessment |
| `source_loaded_at` | nullable date-time | Ingestion timestamp only when supplied and semantically valid; not event time |
| `prediction_generated_at` | nullable date-time | Scoring timestamp only when emitted by a future serving execution |
| `computed_at` | nullable date-time | Read-model materialization time only when an implementation actually records it |
| `sla_state` | required enum | `UNKNOWN`, `FRESH`, or `STALE` |
| `availability` | required enum | `AVAILABLE`, `SOURCE_UNAVAILABLE`, or `OBJECT_UNAVAILABLE` |
| `reason` | nullable string | Required for unavailable/stale states; recommended for `UNKNOWN` |

Current accepted retrospective artifacts do not provide a source watermark suitable for SLA freshness and do not
provide every timestamp above. Until a customer SLA is confirmed, `sla_state` MUST be `UNKNOWN`. The pressure
artifact's `data_freshness` is exactly the forecast origin; it maps only to `origin_date` and MUST NOT support a
`FRESH` claim. Availability is factual and independent from SLA policy.

### 3.5 `SupportState`

Support dimensions remain independent. They MUST NOT be collapsed into a confidence score. A dimension is required
on read models where it applies and otherwise may be null only because it is semantically inapplicable; null never
means supported.

| Field | Enum values when applicable | Meaning |
|---|---|---|
| `forecast_support` | current: `DIRECT`, `PARENT_SCALED`, `DETERMINISTIC_OWN_HISTORY`, `AGGREGATED_PARENT_EVIDENCE`; future reserved: `UNSUPPORTED` | Support/provenance of source forecast evidence before central hierarchy |
| `calibration_support` | `CALIBRATED`, `CALIBRATED_NOT_RECONCILED`, `INSUFFICIENT`, `UNAVAILABLE`, `NATIONAL_PROXY_NOT_A_DISTRIBUTION` | Whether level-local calibrated uncertainty evidence is available and aligned with central derivation |
| `threshold_support` | `HOSPITAL_DATE_CLASS`, `HOSPITAL_POOLED`, `REGION_DATE_CLASS`, `REGION_POOLED`, `UNSUPPORTED` | Origin-legal pressure threshold support/fallback |
| `hierarchy_support` | `CHILD_UNCHANGED`, `BOTTOM_UP_EXACT`, `EXACT_REGION_SUM` | Central hierarchy/coherence semantics only |
| `assessment_support` | `SUPPORTED`, `LIMITED`, `UNSUPPORTED`, `UNKNOWN` | Patient Journey support when derivable; current unknowns remain explicit |
| `anomaly_support` | `SUPPORTED`, `UNSUPPORTED` | Whether the anomaly reference history is adequate |
| `fallback_detail` | nullable source string | Required whenever `forecast_support != DIRECT`; preserves accepted fallback detail |
| `history_total` | nullable number ≥ 0 | Sum of origin-legal target counts used as hierarchy/fallback history |
| `history_nonzero_days` | nullable integer ≥ 0 | Number of origin-legal history days with positive target count |
| `history_days` | nullable integer ≥ 0 | Number of origin-legal calendar days in that history window |

Unavailable dimensions remain explicit. For example, direct forecast support does not imply calibrated uncertainty
or a supported pressure threshold. `threshold_sample_count` is threshold evidence and MUST NOT be substituted for
any of the three forecast-history fields. `forecast_support=UNSUPPORTED` has no accepted current source state and is
reserved for a future serving execution only.

## 4. Vocabulary classification and scalar rules

Classification is normative: **A** = exact source value, **B** = normalized or derived contract value produced by an
explicit deterministic mapping from source evidence, **C** = future placeholder with no current accepted source, and
**D** = unsupported/do not use. A class-B derived value is not a literal source value.

| Concept | Values | Class | Source/mapping rule |
|---|---|---|---|
| `EntityLevel` | `HOSPITAL`, `REGION`, `NATIONAL` | B | Source `hospital/region/national`; profile remains orthogonal |
| `FlowTarget` | `REGISTRATIONS`, `COHORT_HOSPITALIZATIONS` | B | `registrations→REGISTRATIONS`; `cohort_hospitalizations→COHORT_HOSPITALIZATIONS` |
| `EstimandFamily` | `HOSPITALIZATION_CUMULATIVE_INCIDENCE`, `JOINT_COMPETING_RISK`, `REFUSAL_CONDITIONAL_ON_TERMINAL_OUTCOME` | B | Versioned normalization of accepted free-text estimands |
| `CentralForecastSource` | `DIRECT`, `PARENT_SCALED`, `DETERMINISTIC_OWN_HISTORY`, `BOTTOM_UP_SUM` | B | Explicit `forecast_source` mapping in Appendix A |
| `RawQuantileSemantics` | `UNCHANGED_SOURCE_EVIDENCE`, `REGION_QUANTILE_SUM_PROXY`, `DEGENERATE_DETERMINISTIC` | B | Explicit `raw_quantile_semantics` plus uncertainty-support mapping |
| `PressureSeverity` | `UNSUPPORTED`, `NORMAL`, `WATCH`, `ELEVATED`, `HIGH` | A | Exact accepted entity-pressure values |
| `AnomalyStatus` | `UNSUPPORTED`, `NORMAL`, `UNUSUAL_HIGH`, `UNUSUAL_LOW` | A | Exact accepted anomaly values; `UNUSUAL_LOW` is real evidence |
| current threshold provider value | `historical_flow_proxy_v1` | A | Exact `threshold_semantics` value; `provider_id` is a normalized field name |
| `PressureBasis` | `HISTORICAL_FLOW_PROXY` | B | Normalized from `historical_flow_proxy_v1` |
| future pressure provider/basis | `physical_capacity_provider_v1` / `PHYSICAL_CAPACITY` | C | Legal only after real capacity data and independent review |
| `SignalType` | `PREVENTIVE_FLOW_PRESSURE`, `OBSERVED_UNUSUAL_FLOW` | B | `preventive_flow_pressure→PREVENTIVE_FLOW_PRESSURE`; `observed_unusual_flow→OBSERVED_UNUSUAL_FLOW` |
| `MaterialityStatus` | `MATERIALITY_RULE_NOT_TRIGGERED`, `ZERO_BASELINE_LOW_VOLUME` | B | `materiality_rule_not_triggered` and `zero_baseline_low_volume` normalized by case |
| `PrioritySupportClass` | `DIRECT_SUPPORTED`, `FALLBACK_OR_LIMITED_HISTORY` | B | `direct_supported` and `fallback_or_limited_history` normalized by case |
| `InboxQueue` | `PRIMARY`, `UNSUPPORTED_DATA_QUALITY`, `ZERO_BASELINE_LOW_VOLUME_ATTENTION`, `SECONDARY_RESEARCH` | B | Explicit `operational_priority_status` mapping in section 9 |
| `FALLBACK_ATTENTION` as queue | do not use | D | Fallback attention is a derived view over `PRIMARY`, not a queue |
| `ForecastSupport` | `DIRECT`, `PARENT_SCALED`, `DETERMINISTIC_OWN_HISTORY`, `AGGREGATED_PARENT_EVIDENCE` | B | Exact triple mapping in section 6.3 |
| `ForecastSupport.UNSUPPORTED` | future reserved | C | No current accepted source triple maps to it |
| `CalibrationSupport` | `CALIBRATED`, `CALIBRATED_NOT_RECONCILED`, `INSUFFICIENT`, `UNAVAILABLE`, `NATIONAL_PROXY_NOT_A_DISTRIBUTION` | B | Source `uncertainty_status` mapping |
| `ThresholdSupport` | `HOSPITAL_DATE_CLASS`, `HOSPITAL_POOLED`, `REGION_DATE_CLASS`, `REGION_POOLED`, `UNSUPPORTED` | B | Source threshold-fallback strings |
| `CrossingStatus` | `CROSSED`, `NO_CROSSING`, `UNSUPPORTED` | B | Normalizes first-crossing presence plus threshold support |
| `HierarchySupport` | `CHILD_UNCHANGED`, `BOTTOM_UP_EXACT`, `EXACT_REGION_SUM` | B | Source `hierarchy_status` mapping |
| `AssessmentSupport.UNKNOWN` | `UNKNOWN` | B | Deterministically derived contract default because current artifacts do not supply per-assessment serving support; not a literal source value |
| other `AssessmentSupport` values | `SUPPORTED`, `LIMITED`, `UNSUPPORTED` | C | Future adapter vocabulary requiring reviewed evidence rules |
| `AnomalySupport` | `SUPPORTED`, `UNSUPPORTED` | B | `anomaly_status=UNSUPPORTED→UNSUPPORTED`; every other accepted status→`SUPPORTED` |
| central hierarchy `PROXY` | do not use | D | Proxy applies only to raw quantile semantics |
| `FreshnessSlaState` | `UNKNOWN`, `FRESH`, `STALE` | C | Serving policy vocabulary; current artifacts always map to `UNKNOWN` |
| `Availability` | `AVAILABLE`, `SOURCE_UNAVAILABLE`, `OBJECT_UNAVAILABLE` | C | Future serving factual availability vocabulary |
| `AnomalyApplicability` | `APPLICABLE`, `NOT_APPLICABLE` | B | Derived from the target and accepted registrations-only detector configuration; not a literal source value |

All probabilities are finite numbers in `[0,1]`. Served central forecasts, observations, thresholds, and calibrated
interval bounds are finite counts ≥ 0. Raw model quantiles may be negative or crossed because they preserve primary
scientific evidence; an adapter MUST NOT silently clip, sort, or overwrite them. Dates use ISO 8601; date-times
include an offset. Null means unavailable or inapplicable according to the field rule; null MUST NOT be silently
replaced by zero, a global average, certainty, normality, or fresh status.

## 5. `PatientJourneyAssessment`

The contract is candidate-independent and expresses statistical estimands, not AFT, hazard, LightGBM, or other
model classes.

| Field | Type / availability | Semantics |
|---|---|---|
| `assessment_id` | required string | Deterministic identity for the canonical grain |
| `referral` | required `ReferralRef` | Referral reference |
| `estimand_id` | required versioned string | Immutable definition of probability meaning |
| `estimand_family` | required `EstimandFamily` | Governs population, conditioning, legal probability fields, and invariants |
| `prediction_origin_at` | required date-time | Latest information time used for this assessment |
| `hospitalization_probability_7d/14d/30d` | conditionally required probabilities | Legal for hospitalization cumulative incidence and joint competing risk |
| `refusal_probability_7d/14d/30d` | conditionally required probabilities | Legal only for `JOINT_COMPETING_RISK` |
| `unresolved_probability_7d/14d/30d` | conditionally required probabilities | Legal only for `JOINT_COMPETING_RISK` |
| `refusal_probability_given_terminal_outcome` | conditionally required probability | Single horizon-free probability for `REFUSAL_CONDITIONAL_ON_TERMINAL_OUTCOME` |
| `model_version` | required string | Immutable predictive artifact identity |
| `calibration_version` | nullable string | Null only when no calibration applies/is available |
| `support` | required `SupportState` | Applicable support dimensions; inapplicable flow-only dimensions remain documented as unavailable |
| `freshness` | required `Freshness` | No implicit SLA freshness |
| `provenance` | required `Provenance` | Accepted run/artifact lineage |

Rules:

- For a model-owned assessment, `PatientJourneyAssessment.model_version` is the direct authoritative immutable model
  artifact reference and MUST exactly match `PatientJourneyAssessment.provenance.model_version`. Conflicting or
  duplicate model identities are invalid. `Provenance.model_version` remains nullable for objects that are not
  directly model-owned or whose historical lineage is incomplete.

- `HOSPITALIZATION_CUMULATIVE_INCIDENCE` emits cumulative hospitalization probabilities at 7/14/30 days. It MUST
  NOT synthesize `1 - P(hospitalized)` as unresolved or refusal.
- `REFUSAL_CONDITIONAL_ON_TERMINAL_OUTCOME` is the accepted refusal LightGBM estimand: probability of refusal
  conditional on an observed terminal referral outcome. It is horizon-free, is not a marginal
  `P(refusal <= 7/14/30d)`, and MUST NOT emit per-horizon refusal fields.
- A conditional refusal probability MUST NOT be displayed beside hospitalization horizon probabilities in a way
  that implies comparability, a common denominator, or joint coherence.
- Independently produced hospitalization and refusal assessments MUST NOT be combined into a pseudo-joint
  distribution. UI/adapters MUST NOT join assessments with different `estimand_id` values into one display that
  implies a single distribution.
- Only `JOINT_COMPETING_RISK` may emit per-horizon hospitalization, refusal, and unresolved probabilities and claim
  that those states are mutually exclusive and sum to one at each horizon within documented numerical tolerance.
- The only accepted current joint implementation is the empirical competing-risk/Aalen–Johansen-style baseline with
  its documented low-support fallback. The individual ML hospitalization and conditional-refusal models do not
  implement this joint estimand. The ML joint challenger was not promoted.
- Probability semantics change only through a new `estimand_id`; changing a model or calibration artifact alone
  does not require changing the public schema.
- Current artifacts do not provide per-assessment serving support, so `assessment_support` remains `UNKNOWN` rather
  than being inferred from aggregate test/subgroup metrics.
- 6B.2A retained AFT and discrete-hazard evidence pending a serving tradeoff. This contract selects neither.

## 6. `FlowForecastPoint` and `FlowForecastSeries`

### 6.1 Point fields

| Field | Type / availability | Semantics |
|---|---|---|
| `entity` | required `EntityRef` | Forecasted hierarchy series |
| `target` | required `FlowTarget` | Count estimand |
| `origin_date` | required date | Last observed date |
| `target_date` | required date | Forecasted date |
| `horizon_days` | required integer 1–14 | `target_date - origin_date` |
| `forecast_value` | required count | Accepted central operational forecast |
| `central_source` | required `CentralForecastSource` | Explicit normalized mapping from accepted `forecast_source` |
| `central_adjusted_from_source` | required boolean | Exact mapping from `hierarchy_adjusted` |
| `raw_quantiles` | nullable `RawQuantileEvidence` | Raw scientific evidence; never overwritten by calibration or repair |
| `calibrated_uncertainty` | nullable `CalibratedUncertainty` | Separate level-local uncertainty object |
| `probabilistic_reconciliation_applied` | required boolean | `false` for accepted 6B.2B artifacts |
| `support` | required `SupportState` | Independent support dimensions |
| `freshness` | required `Freshness` | Availability and SLA policy remain separate |
| `provenance` | required `Provenance` | Accepted source chain |

In accepted 6B.2B/6B.2C artifacts `RawQuantileEvidence` always has numeric `p10`, `p50`, and `p90`. Future serving
objects may set `raw_quantiles=null` only when no probabilistic source exists; they MUST NOT fabricate values. Values
with `UNCHANGED_SOURCE_EVIDENCE` preserve raw model/statistical evidence. Values with
`REGION_QUANTILE_SUM_PROXY` semantics are sums of corresponding region quantiles: they are display/diagnostic
proxies, not mathematically valid national quantiles or a national predictive distribution. Values with
`DEGENERATE_DETERMINISTIC` have `p10=p50=p90` from deterministic own-history fallback and MUST carry source detail
`degenerate_interval_no_estimated_uncertainty_support`; they are not estimated probabilistic uncertainty.

`CalibratedUncertainty` contains required `lower`, `upper`, `nominal_coverage`, and `calibration_version`.
It is level-local uncertainty evidence and human-facing terminology is **uncertainty range**, not relabelled p10/p90
or a confidence interval. `nominal_coverage` is the configured calibration target, not achieved empirical coverage;
it MUST NOT be displayed as “achieved 80% coverage”, “80% confidence”, or a guaranteed 80% interval. Retrospective
coverage metrics do not attach to individual serving predictions.

After central hierarchy adjustment, `forecast_value` and the level-local interval may have different derivation
paths. The interval is not guaranteed to contain `forecast_value`; clients MUST NOT assume
`lower <= forecast_value <= upper`, describe it as centered on the served central, or shift/repair it around central.
If unavailable, the entire object is null and `calibration_support` explains why.

### 6.2 Series fields and invariants

`FlowForecastSeries` contains required `entity`, `target`, `origin_date`, `points`, `freshness`, and `provenance`.
Points MUST have unique target dates and horizons, share the wrapper identity, and be ordered by horizon. Series-level
freshness and provenance are legal only when identical for every point; otherwise each point MUST carry them and the
wrapper MUST NOT imply one common value.

- `REGISTRATIONS` is referral inflow.
- `COHORT_HOSPITALIZATIONS` is hospitalization events attributable to the Q1 referral cohort. Early January is
  structurally incomplete because pre-2025 registrations are absent.
- Neither target means total admissions, occupancy, census, free beds, staffed beds, or capacity.
- Accepted central hierarchy is exact under `BOTTOM_UP_SUM`; this does not establish probabilistic reconciliation.
- Raw quantiles and calibrated intervals remain unchanged level-local evidence when a central value is adjusted.
- Ninety days of registration history supports short-term/weekday evidence only, not annual seasonality.

### 6.3 Explicit source mappings

Central-source normalization:

| Accepted `forecast_source` | `CentralForecastSource` | Mapping |
|---|---|---|
| `direct_quantile_ml` | `DIRECT` | NORMALIZED |
| `parent_scaled_direct_quantile_ml` | `PARENT_SCALED` | NORMALIZED; region-share fallback, not hierarchy reconciliation |
| `deterministic_own_history_fallback` | `DETERMINISTIC_OWN_HISTORY` | NORMALIZED |
| `bottom_up_hospital_sum` | `BOTTOM_UP_SUM` | NORMALIZED; region central is exact hospital sum |
| `exact_region_central_sum` | `BOTTOM_UP_SUM` | NORMALIZED; national central is exact region sum |

Forecast-support/fallback normalization uses the complete accepted source tuple:

| `support_status` | `fallback_status` | `prediction_source` | `forecast_support` | `fallback_detail` |
|---|---|---|---|---|
| `supported` | `not_applicable` | `direct_quantile_ml` | `DIRECT` | null |
| `limited_history` | `regional_fallback` | `parent_scaled_direct_quantile_ml` | `PARENT_SCALED` | `regional_fallback` |
| `no_history` | `regional_fallback` | `parent_scaled_direct_quantile_ml` | `PARENT_SCALED` | `regional_fallback` |
| `no_history` | `no_history_deterministic_zero` | `deterministic_own_history_fallback` | `DETERMINISTIC_OWN_HISTORY` | `no_history_deterministic_zero` |
| `supported` | `national_historical_quantile_proxy` | `region_quantile_sum_proxy` | `AGGREGATED_PARENT_EVIDENCE` | `national_historical_quantile_proxy` |

No accepted tuple maps to `forecast_support=UNSUPPORTED`. Unknown tuples MUST fail mapping rather than be coerced.
Source `history_total`, `history_nonzero_days`, and `history_days` map one-to-one to the same contract fields.

Central hierarchy normalization is independent:

| `hierarchy_status` | `hierarchy_support` | Meaning |
|---|---|---|
| `bottom_up_child_unchanged` | `CHILD_UNCHANGED` | Hospital central retained under selected bottom-up contract |
| `bottom_up_exact` | `BOTTOM_UP_EXACT` | Region central is exact hospital sum |
| `exact_region_sum` | `EXACT_REGION_SUM` | National central is exact region sum |

`hierarchy_adjusted` maps losslessly to `central_adjusted_from_source`. Raw-quantile proxy semantics never map to
this central hierarchy axis. `probabilistic_reconciliation_applied` remains explicitly `false`.

Calibration-support normalization:

| `uncertainty_status` | `calibration_support` | Interval object |
|---|---|---|
| `level_local_calibrated` | `CALIBRATED` | present |
| `level_local_calibrated_not_reconciled` | `CALIBRATED_NOT_RECONCILED` | present; not moved with central |
| `calibration_support_insufficient` | `INSUFFICIENT` | null |
| `uncertainty_unavailable` | `UNAVAILABLE` | null |
| `national_proxy_not_predictive_distribution` | `NATIONAL_PROXY_NOT_A_DISTRIBUTION` | null |

Raw-quantile normalization:

| Source evidence | `RawQuantileSemantics` |
|---|---|
| `raw_quantile_semantics=unchanged_model_evidence` and estimated uncertainty support | `UNCHANGED_SOURCE_EVIDENCE` |
| `raw_quantile_semantics=historical_region_quantile_sum_proxy_not_national_distribution` | `REGION_QUANTILE_SUM_PROXY` |
| `prediction_source=deterministic_own_history_fallback` and `uncertainty_support=degenerate_interval_no_estimated_uncertainty_support` | `DEGENERATE_DETERMINISTIC` |

## 7. `PressureSignal`

`PressureSignal` is one consolidated preventive signal. Daily forecast cells may be referenced as evidence but MUST
NOT become separately ranked serving signals.

| Field | Type / availability | Semantics |
|---|---|---|
| `signal_id` | required string | Deterministic signal identity |
| `signal_type` | required constant | `PREVENTIVE_FLOW_PRESSURE` |
| `entity` | required hospital/profile `EntityRef` | Signal subject |
| `target` | required `FlowTarget` | `REGISTRATIONS` primary; cohort target remains secondary/research |
| `origin_date` | required date | Forecast origin |
| `severity` | required `PressureSeverity` | Source pressure severity, immutable under product triage |
| `pressure_basis` | required `PressureBasis` | Current value is `HISTORICAL_FLOW_PROXY` |
| `provider_id` | required string | Current value is `historical_flow_proxy_v1` |
| `threshold_semantics` | required string | Versioned method semantics |
| `threshold_value` | nullable count | Required unless threshold support is `UNSUPPORTED` |
| `threshold_evidence` | nullable object | Reproduction evidence when carried from the selected daily cell |
| `severity_window_days` | required integer | Current consolidated severity window is 14 |
| `severity_evidence_date` | required date | Earliest target date attaining the maximum 14-day severity |
| `severity_evidence_horizon` | required integer 1–14 | Earliest horizon attaining the maximum 14-day severity |
| `first_crossing_severity` | nullable `PressureSeverity` | Severity at first alert crossing; null exactly when no supported crossing exists |
| `first_crossing_date` | nullable date | First warning crossing, if any |
| `lead_time_days` | nullable integer | First-crossing horizon, if any |
| `crossing_status` | required `CrossingStatus` | Distinguishes no crossing from unsupported evidence |
| `any_alert_7d` | required boolean | Any `WATCH/ELEVATED/HIGH` cell in horizons 1–7 |
| `any_alert_14d` | required boolean | Any `WATCH/ELEVATED/HIGH` cell in horizons 1–14 |
| `max_severity_7d` | required `PressureSeverity` | Maximum source severity in horizons 1–7 |
| `max_severity_14d` | required `PressureSeverity` | Maximum source severity in horizons 1–14; equals `severity` |
| `forecast_value` | required count | Central evidence at the severity evidence date |
| `uncertainty_lower/upper` | nullable counts | Both from the same evidence cell; null when unavailable |
| `reason_codes` | required list of strings | Deterministic, non-causal source reasons |
| `support` | required `SupportState` | Includes threshold fallback independently from forecast/calibration |
| `freshness` | required `Freshness` | No implicit SLA freshness |
| `provenance` | required `Provenance` | Pressure plus forecast lineage |

The signal-level `support.threshold_support`, `threshold_value`, and `threshold_evidence` describe the single daily
cell identified by `severity_evidence_date` and `severity_evidence_horizon`. They are not a universal threshold state
for every day in the 14-day window: the applicable fallback rung may differ by target day/date class. Reproduction
MUST resolve threshold evidence from that same severity evidence cell.

Current severity semantics are `NORMAL` below threshold, `WATCH` when only the calibrated upper bound exceeds,
`ELEVATED` when the central forecast exceeds, `HIGH` when the calibrated lower bound exceeds, and `UNSUPPORTED`
without threshold support. Missing uncertainty cannot create `WATCH` or `HIGH`.

`threshold_evidence`, when available, contains the selected cell's `threshold_date_class`,
`threshold_sample_count`, `threshold_positive_days`, `threshold_history_start`, `threshold_history_end`, and
`threshold_quantile`. These reproduce threshold provenance and remain separate from general forecast-history fields.
For a supported signal, null `lead_time_days` means `crossing_status=NO_CROSSING`; threshold-unsupported signals use
`crossing_status=UNSUPPORTED`, so the two cases cannot be conflated.

The entity-pressure-signals artifact does not directly store `history_total`, `history_nonzero_days`, or
`history_days`. A future `PressureSignal` adapter MAY populate them only by joining the corresponding
hierarchy/forecast source evidence cell; otherwise it MUST leave them null. It MUST NOT manufacture them or use
`threshold_sample_count` as a substitute.

Threshold support maps explicitly:

| Source `threshold_fallback_level` | `ThresholdSupport` |
|---|---|
| `hospital_date_class` | `HOSPITAL_DATE_CLASS` |
| `hospital_pooled` | `HOSPITAL_POOLED` |
| `region_date_class` | `REGION_DATE_CLASS` |
| `region_pooled` | `REGION_POOLED` |
| `unsupported_insufficient_history` | `UNSUPPORTED` |

`historical_flow_proxy_v1` compares with origin-legal historical flow. It is not a physical-capacity model. A future
`physical_capacity_provider_v1` MAY implement the same semantic interface only after real physical-capacity data and
its interpretation are agreed.

## 8. `ObservedAnomaly`

| Field | Type / availability | Semantics |
|---|---|---|
| `anomaly_id` | required string | Source identity hash of detector version × origin × `series_id` |
| `signal_type` | required constant | `OBSERVED_UNUSUAL_FLOW` |
| `entity` | required hospital/profile `EntityRef` | Observed series |
| `target` | required `FlowTarget` | Accepted configuration fixes `REGISTRATIONS`; target is not a source identity column |
| `observation_date` | required date | Date of the observed value, not a future forecast target |
| `anomaly_status` | required `AnomalyStatus` | Own namespace; never `PressureSeverity` |
| `observed_value` | required count | Observed operational count |
| `reference_evidence` | required object | Weekly residual, reference median/MAD/sample count/max date; `robust_z` nullable only when unsupported |
| `reason_codes` | required list of strings | Deterministic, non-causal reasons |
| `evidence_facts` | required list of strings | Operator-facing facts, not causal explanations |
| `support` | required `SupportState` | Unsupported history stays visible |
| `freshness` | required `Freshness` | Observation availability; SLA state remains unknown |
| `provenance` | required `Provenance` | Detector and source lineage |

An observed anomaly answers “is unusual flow observed now?” Pressure answers “is high historical-flow pressure
expected ahead?” An anomaly MAY be attached as context but MUST NOT modify pressure severity or Inbox rank.
`UNUSUAL_LOW` is part of accepted evidence. The experimental artifact also emits a pressure-style `severity` and
maps both high and low flags to `ELEVATED` for representative presentation. That column, including merged
`severity_x/severity_y`, is SERVING_ILLEGAL; only `anomaly_status` defines the serving anomaly state.

## 9. `SignalInboxItem`

| Field | Type / availability | Semantics |
|---|---|---|
| `signal_ref` | required string | Reference to exactly one `PressureSignal` |
| `origin_date` | required date | Ranking partition component |
| `target` | required `FlowTarget` | Ranking partition component |
| `inbox_rank` | nullable positive integer | Required for `PRIMARY`; null for non-ranked queues |
| `queue` | required `InboxQueue` | Product triage classification |
| `source_severity` | required `PressureSeverity` | Immutable source pressure severity |
| `materiality_status` | required `MaterialityStatus` | Product triage, not source science |
| `materiality_floor_expected_count` | required number | Current fixed rule is `1.0` expected count/day |
| `priority_support_class` | required `PrioritySupportClass` | Direct-supported or fallback/limited-history presentation class |
| `lead_time_days` | nullable integer | Preserved source first-crossing lead |
| `headline` | required string | Deterministic, non-causal text |
| `concise_reason` | required string | Deterministic source/support explanation |
| `reason_codes` | required list of strings | Source reason codes retained |
| `evidence_facts` | required list of strings | Facts from the same severity evidence cell |
| `observed_anomaly_ref` | nullable string | Context only |
| `observed_anomaly_applicability` | required enum | `APPLICABLE` only for registrations under the accepted detector |
| `observed_anomaly_present` | nullable boolean | Null when not applicable; otherwise true only for a same-origin flagged anomaly |
| `support` | required `SupportState` | Forecast/calibration/threshold/hierarchy states remain separate |
| `freshness` | required `Freshness` | No implicit SLA freshness |
| `provenance` | required `Provenance` | Prioritization and source-pressure lineage |

Ranking is fixed lexicographic: source severity, shorter lead time, direct/support class, calibrated uncertainty
availability, valid positive-threshold central/threshold ratio, then stable entity IDs. There is no learned ranker,
weighted score, validation/final tuning, or 0–100 “AI score”. A zero/missing threshold never produces an infinite or
NaN priority advantage.

Queue mapping is exact and mutually exclusive:

| Source `operational_priority_status` | Contract `queue` | Rule |
|---|---|---|
| `primary_inbox_eligible` | `PRIMARY` | Supported, material primary-target warning |
| `unsupported_data_quality` | `UNSUPPORTED_DATA_QUALITY` | Primary target lacks threshold support |
| `zero_baseline_low_volume` | `ZERO_BASELINE_LOW_VOLUME_ATTENTION` | Primary-target source warning also meets materiality preconditions |
| `secondary_research_evidence` | `SECONDARY_RESEARCH` | Cohort-hospitalization evidence, never primary ranking |
| `not_a_primary_warning` | no `SignalInboxItem` | Supported `NORMAL` registrations do not create Inbox rows |

`FALLBACK_ATTENTION` is not an `InboxQueue`. It is the derived filter
`queue=PRIMARY AND priority_support_class=FALLBACK_OR_LIMITED_HISTORY`; the same item retains its primary
`inbox_rank`.

Materiality and queue placement are independent decisions. `materiality_status` is computed from supported
threshold/forecast evidence before target/severity queue rules. `ZERO_BASELINE_LOW_VOLUME` alone does not imply the
attention queue: that queue also requires registrations, an alert severity, and supported threshold evidence. A
cohort-hospitalization row may legally have `materiality_status=ZERO_BASELINE_LOW_VOLUME` and
`queue=SECONDARY_RESEARCH`.

For applicable registration items, `observed_anomaly_present=true` means a flagged `UNUSUAL_HIGH` or `UNUSUAL_LOW`
anomaly exists at the same origin for the same hospital/profile `series_id`; a merely existing `NORMAL` or
`UNSUPPORTED` anomaly record produces false. For non-registration targets, applicability is `NOT_APPLICABLE` and
the boolean is null. Observed anomaly context is never a ranking key.

Accepted evaluation ranking uses `(phase, origin, target)`. Dropping `phase` from the serving partition is lossless
for these accepted runs only because each origin belongs to exactly one phase. A future execution must enforce one
row partition per origin rather than assume this property silently.

## 10. Serving execution versus evaluation execution

Evaluation artifacts MAY contain folds, outcomes, labels, candidate names, and metrics. Serving objects MUST contain
only information available at or before their declared origin/observation plus immutable lineage.

No accepted 6B.2B/6B.2C artifact row is directly serving-eligible. The accepted runs are retrospective evaluations at
fixed legal origins. Removing `phase`, `y`, `actual_*`, `evaluation_supported_*`, or other retrospective columns does
not transform an evaluation row into a production serving object.

The following artifact fields are serving-illegal and MUST be stripped by a future adapter:

- `phase`, `validation`, `final_test`, fold/trial/candidate-selection labels;
- `y`, `actual_exceeds_threshold`, `actual_event_within_7d/14d`;
- `evaluation_supported_7d/14d`, precision, recall, false-alert rate, and retrospective metrics;
- any presentation-only merged suffix such as `severity_x` or `severity_y`.

Serving objects use a legal `origin_date`, only timestamps actually emitted by the serving execution, and explicit
availability/SLA state. Evaluation phase MUST NOT be repurposed as a live environment, queue, status, or provenance
field.

A future implementation requires a dedicated legal-origin scoring execution mode that scores a current origin,
does not require future outcomes, emits only a reviewed serving whitelist, verifies source lineage, and publishes
atomically. That path is FUTURE CODE WORK and requires independent review before publication; this specification
does not claim it exists.

## 11. Cross-model invariants and forbidden interpretations

The following are acceptance tests for future persistence/API/UI work:

1. Raw p10/p50/p90 are not a calibrated uncertainty range.
2. Exact central hierarchical coherence is not probabilistic reconciliation.
3. Preventive pressure is not an observed anomaly.
4. Source pressure severity is not materiality status or queue classification.
5. Forecast, calibration, hierarchy, and threshold support remain independent.
6. Registrations differ from cohort hospitalizations; cohort hospitalizations are not total admissions, occupancy,
   free beds, census, or capacity.
7. Independent hospitalization/refusal marginals are not a validated joint competing-risk distribution.
8. Current internal IDs are not confirmed stable government source IDs.
9. Serving outputs contain no retrospective outcomes or evaluation labels.
10. Public semantics contain no model-family dependency.
11. Unknown refresh SLA cannot silently imply `FRESH`.
12. No physical-capacity claim is legal without physical-capacity data and a reviewed provider contract.
13. Inbox priority is deterministic and contains no learned/weighted score.
14. Null/unsupported/unknown states are never silently converted to zero, normal, certain, direct, or fresh.
15. Conditional terminal-outcome refusal probability is not a horizon probability and is not jointly coherent with
    an independent hospitalization assessment.
16. A level-local calibrated interval need not contain the hierarchy-adjusted central forecast.
17. Evaluation-field removal alone never makes an accepted retrospective row serving-eligible.

## 12. Legacy compatibility boundary

The existing backend and frontend implement an older product generation and remain unchanged by 6B.2D:

- `app.schemas.common.Status` is lower-case `high/elevated/normal/insufficient_data` derived from the legacy
  `load_index`; it is not `PressureSeverity`.
- `app.schemas.status.Forecast` exposes two central 14-day series and a method/version; it does not express raw
  quantiles, calibrated uncertainty, hierarchy support, or the 6B.2D target semantics.
- `app.schemas.activity.ReferralItem` exposes legacy wait/refusal predictions for test-period referrals; it is not
  `PatientJourneyAssessment` and lacks `estimand_id`.
- `app.schemas.activity.AlertItem` and `GET /alerts` select legacy load-index or queue-trend rows. They are not
  `PressureSignal` or `SignalInboxItem`.

Future integration MUST be additive and versioned. It MUST NOT redefine these classes or `/alerts` in place. Old
endpoints remain compatible until a reviewed Control Tower migration explicitly deprecates/replaces them.

## 13. Future integration guidance

After independent acceptance of this draft:

1. define framework-independent domain/read-model types and artifact adapters with invariant tests;
2. define an atomic, versioned batch publication contract and only then add Alembic-owned read tables if needed;
3. add candidate-independent Pydantic schemas and additive endpoints;
4. regenerate OpenAPI and TypeScript transport deterministically, then map into UI view models;
5. expose unsupported, fallback, freshness, and degraded states explicitly;
6. retain human review, source lineage, and old endpoint compatibility throughout migration;
7. keep explanation deterministic and usable without an external LLM in the serving critical path.

PostgreSQL is the intended durable read-model boundary, but no table or publication cadence is selected here.
Training/model code remains outside the HTTP process. Model promotion and operational action remain human-controlled.

## 14. Confirmed pre-integration corrective items

These findings are recorded, not fixed by this specification task:

1. `pressure.py` currently emits anomaly `anomaly_status` and also reuses a `severity` column. Its representative
   example merge creates `severity_x`/`severity_y`. The serving adapter must use only `anomaly_status`, remove the
   pressure-severity namespace from anomaly DTOs, and use explicit future-pressure context fields. Accepted 6B.2C
   science and artifacts remain unchanged.
2. Patient Journey's `_future_serving_contract()` still uses legacy draft names
   `support_confidence_metadata`, `prediction_timestamp`, `data_freshness_metadata`, grouped
   `refusal_probability_7d_14d_30d` / `unresolved_probability_7d_14d_30d`, omits `estimand_id`, and saved evidence
   uses free-text `estimand`. It also fails to represent the horizon-free conditional refusal estimand. A reviewed,
   versioned estimand registry and adapter are required before serving; no champion is inferred and ML code is not
   changed here.
3. Accepted flow/pressure/prioritization artifacts contain evaluation-only fields (`phase`, `y`, `actual_*`,
   `evaluation_supported_*`). A future serving publication must whitelist legal fields rather than expose artifact
   rows directly.
4. Current `data_freshness` values are origin dates, not an agreed SLA evaluation or complete timestamp object.
   They map only to `Freshness.origin_date`; `sla_state` remains `UNKNOWN` until customer rules exist.
5. Accepted prioritization rows encode `observed_anomaly_present=false` for non-registration targets because the
   experimental merge is registrations-only. A future adapter must normalize those cases to not-applicable/null, not
   treat false as evidence that anomaly assessment occurred.

## 15. Customer unknowns

The following remain unresolved and MUST NOT be filled by assumption:

- production user and production owner;
- stable referral ID and stable organization ID;
- source of truth and integration mode (API, database, bus, or batch);
- refresh SLA;
- physical-capacity data;
- process KPI, baseline, and target;
- allowed operational recommendations;
- closed-contour requirements;
- SSO/IdP, roles, and retention;
- Kazakhstan/Russian language and localization requirements;
- deployment target and hardware budget;
- monitoring stack and retraining expectation;
- license restrictions and support owner.

## Appendix A. Accepted artifact → contract mapping

Each mapping is classified as `LOSSLESS`, `NORMALIZED`, `CONDITIONAL`, `LOSSY`, `SERVING_ILLEGAL`, or
`FUTURE_ONLY`. `NORMALIZED` preserves meaning through an explicit vocabulary mapping; `CONDITIONAL` requires the
stated source checks.

### A.1 Identity, flow, hierarchy, and uncertainty

| Current accepted source | 6B.2D field | Class | Rule |
|---|---|---|---|
| `level`, `series_id`, `org_code`, `region_code`, `profile_code` | `EntityRef` | NORMALIZED | Map level to `HOSPITAL/REGION/NATIONAL`; set provisional `id_scheme=internal_derived_v1` |
| `origin`, `target_date`, `horizon` | flow origin/target/horizon | LOSSLESS | Preserve date values; require date difference equals horizon |
| `target=registrations/cohort_hospitalizations` | `FlowTarget` | NORMALIZED | Upper-case enum only; semantics unchanged |
| raw `p10/p50/p90` | `raw_quantiles.p10/p50/p90` | LOSSLESS | Never clip, sort, or replace |
| `raw_quantile_semantics=unchanged_model_evidence` | `UNCHANGED_SOURCE_EVIDENCE` | NORMALIZED | Unless deterministic-degenerate rule below applies |
| `historical_region_quantile_sum_proxy_not_national_distribution` | `REGION_QUANTILE_SUM_PROXY` | NORMALIZED | Never a national distribution or central hierarchy state |
| deterministic source plus `degenerate_interval_no_estimated_uncertainty_support` | `DEGENERATE_DETERMINISTIC` | NORMALIZED | Equal p10/p50/p90 do not estimate uncertainty |
| `forecast_value` | central `forecast_value` | LOSSLESS | Accepted hierarchy-selected central value |
| `forecast_source` | `CentralForecastSource` | NORMALIZED | Use the five-row table in section 6.3 |
| `hierarchy_adjusted` | `central_adjusted_from_source` | LOSSLESS | Preserve boolean exactly |
| `hierarchy_status` | `hierarchy_support` | NORMALIZED | Map only to child-unchanged/bottom-up-exact/exact-region-sum |
| central hierarchy `PROXY` | none | SERVING_ILLEGAL | No such accepted central state; proxy is raw-quantile semantics only |
| `support_status`, `fallback_status`, `prediction_source` | `forecast_support`, `fallback_detail` | NORMALIZED | Complete accepted tuple table in section 6.3; reject unknown tuples |
| `history_total` | same support field | LOSSLESS | Origin-legal target-count sum |
| `history_nonzero_days` | same support field | LOSSLESS | Positive-flow history-day count |
| `history_days` | same support field | LOSSLESS | Calendar history-day count |
| `uncertainty_status` | `calibration_support` | NORMALIZED | Preserve `CALIBRATED_NOT_RECONCILED`; use section 6.3 table |
| level-local interval lower/upper | `CalibratedUncertainty.lower/upper` | LOSSLESS | Do not force interval to contain central |
| `calibration_nominal_coverage` | `nominal_coverage` | LOSSLESS | Calibration target only, never achieved coverage/confidence |
| `calibration_version` | same | LOSSLESS | Immutable calibration reference |
| retrospective calibration coverage/metrics | none on a forecast point | SERVING_ILLEGAL | Assurance/evaluation views only |
| `probabilistic_reconciliation_applied=false` | same | LOSSLESS | Required false for accepted chain |

### A.2 Pressure and threshold evidence

| Current accepted source | 6B.2D field | Class | Rule |
|---|---|---|---|
| daily pressure `signal_id` | evidence reference only | CONDITIONAL | Daily cell is not a consolidated signal identity |
| entity `signal_id`, lower-case `signal_type`, IDs, `origin`, `target` | pressure identity/type/entity/origin/target | NORMALIZED | Signal type enum normalization only |
| entity `severity` | `PressureSignal.severity` | LOSSLESS | Exact `PressureSeverity` source value |
| `max_severity_14d` | same and `severity_window_days=14` | LOSSLESS | Must equal `severity` |
| `max_severity_7d` | same | LOSSLESS | Preserve source summary |
| `any_alert_7d`, `any_alert_14d` | same | LOSSLESS | Preserve source booleans |
| `first_crossing_severity` | same | LOSSLESS | Null only when no alert crossing |
| `first_crossing_date`, `lead_time_days` plus threshold support | crossing fields/status | NORMALIZED | Distinguish `NO_CROSSING` from `UNSUPPORTED` |
| `severity_evidence_horizon/date` | same | LOSSLESS | Earliest horizon/date attaining 14-day maximum severity |
| entity forecast/threshold/interval/reason fields | same pressure evidence fields | LOSSLESS | All values must reproduce severity from one evidence cell |
| `threshold_semantics=historical_flow_proxy_v1` | provider value and `HISTORICAL_FLOW_PROXY` | NORMALIZED | Exact value preserved; basis normalized; not capacity |
| `threshold_fallback_level` | `threshold_support` | NORMALIZED | Map four supported rungs plus unsupported |
| daily threshold fallback/value/date class/sample/positive days/history window/quantile | signal threshold support/value/evidence | CONDITIONAL | Copy only from the verified severity evidence cell; the fallback rung may differ on other target days |
| threshold `threshold_sample_count` | same threshold-evidence field | LOSSLESS | Never general forecast history |
| hierarchy/forecast `history_total`, `history_nonzero_days`, `history_days` | optional pressure support history fields | CONDITIONAL | Not stored directly on entity pressure rows; join the corresponding source evidence cell or leave null, never manufacture |
| `phase`, `y`, `actual_exceeds_threshold`, `actual_event_within_*`, `evaluation_supported_*` | none | SERVING_ILLEGAL | Retrospective/evaluation-only |

### A.3 Anomaly and Inbox

| Current accepted source | 6B.2D field | Class | Rule |
|---|---|---|---|
| anomaly `signal_id` | `anomaly_id` | LOSSLESS | Identity already hashes detector version × origin × series |
| configured `anomaly.target=registrations`; no row target | `ObservedAnomaly.target=REGISTRATIONS` | CONDITIONAL | Verify accepted detector configuration |
| anomaly `forecast_origin` | `observation_date` and freshness origin | NORMALIZED | Contemporaneous observation date, not future target |
| `anomaly_status` including `UNUSUAL_LOW` | same enum | LOSSLESS | Sole serving anomaly state |
| anomaly `severity`, `severity_x`, `severity_y` | none | SERVING_ILLEGAL | Pressure namespace reuse/presentation merge |
| observed value, weekly residual, median, MAD, sample count, max reference date | anomaly/reference evidence | LOSSLESS | Non-causal source facts |
| anomaly `robust_z` | reference evidence | CONDITIONAL | Nullable when source support is inadequate |
| prioritization `signal_id` | `SignalInboxItem.signal_ref` | LOSSLESS | References one pressure signal |
| `source_severity` | same | LOSSLESS | Never rewritten by materiality/queue |
| `materiality_status`, materiality floor | same normalized fields | NORMALIZED | Independent from queue decision |
| four supported `operational_priority_status` strings | `InboxQueue` | NORMALIZED | Exact table in section 9 |
| `not_a_primary_warning` | no Inbox item | NORMALIZED | Supported normal registration rows omitted |
| `fallback_attention` artifact view | derived filter over `PRIMARY` | NORMALIZED | Not a queue; filter on fallback support class |
| `inbox_rank` | same | LOSSLESS | Present for primary ranked warnings; null for non-ranked queues |
| `priority_support_class` | same normalized enum | NORMALIZED | Preserve direct vs fallback/limited distinction |
| headline/reason/reason codes/evidence facts | same | LOSSLESS | Deterministic and non-causal |
| registrations `observed_anomaly_present/status` | applicability/presence/ref | CONDITIONAL | True only for same-origin flagged high/low anomaly |
| non-registration `observed_anomaly_present=false` | applicability `NOT_APPLICABLE`, presence null | LOSSY | Accepted artifact conflates not-applicable with false; adapter must correct from target semantics |
| prioritization `phase`, copied `actual_event_*`, `evaluation_supported_*` | none | SERVING_ILLEGAL | Retrospective/evaluation-only |

### A.4 Patient Journey and provenance

| Current accepted source | 6B.2D field | Class | Rule |
|---|---|---|---|
| free text “cumulative incidence of hospitalization…” | `HOSPITALIZATION_CUMULATIVE_INCIDENCE` plus versioned `estimand_id` | NORMALIZED | Registry definition required; no guessed ID |
| free text “three-state distribution…” | `JOINT_COMPETING_RISK` plus versioned `estimand_id` | NORMALIZED | Current accepted implementation is empirical baseline only |
| refusal free text “probability of refusal conditional on an observed terminal referral outcome” | `REFUSAL_CONDITIONAL_ON_TERMINAL_OUTCOME` | NORMALIZED | One horizon-free conditional field |
| draft hospitalization horizon fields | same explicit horizon fields | CONDITIONAL | Legal under hospitalization or joint estimand only |
| grouped `refusal_probability_7d_14d_30d` placeholder | joint estimand's three explicit horizon fields only | LOSSY | Cannot represent conditional refusal; legacy draft name must not serve |
| grouped `unresolved_probability_7d_14d_30d` placeholder | joint estimand's three explicit horizon fields | LOSSY | Expand only under verified joint estimand |
| `support_confidence_metadata`, `prediction_timestamp`, `data_freshness_metadata` | support/prediction origin/freshness | LOSSY | Legacy draft placeholders require reviewed adapter semantics |
| candidate/family/parameters/test metrics | provenance/assurance only | SERVING_ILLEGAL | Model-family and evaluation detail are not public serving fields |
| run `code.source.sha256` / scientific `code_identity` | `Provenance.code_identity` | LOSSLESS | Producing scientific source SHA256 |
| run `git_commit` | `Provenance.git_commit` | LOSSLESS | Assurance metadata, not code identity |
| run `dirty_worktree` | `Provenance.dirty_worktree` | LOSSLESS | Assurance metadata, not code identity |
| checkpoint/artifact `sha256` | `Provenance.artifact_identity` | LOSSLESS | Published artifact content identity |
| registry artifact/version | `Provenance.model_version` | CONDITIONAL | Present only for a model-owned prediction |
| future timestamps, SLA decision, legal-origin serving run | freshness/serving provenance | FUTURE_ONLY | Must come from future reviewed execution; never invented from retrospective artifacts |

## Appendix B. Source authority

This accepted contract follows the 2026-09-19 authoritative handoff and project evidence index. Stage-specific documents remain
the detailed scientific references. If an older artifact or document conflicts with the accepted run chain or the
invariants above, it does not override this contract.
