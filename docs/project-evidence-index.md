# Project Evidence Index
## Hospital Flow Control Tower — GovTech Camp 2026

> Purpose: fast navigation from capability to accepted evidence.  
> This is an index, not a replacement for stage-specific documentation or run artifacts.  
> Do not use superseded experimental runs when a later accepted run is listed here.

---

## 1. Evidence policy

For every capability distinguish:

1. **code / config**
2. **documentation**
3. **accepted real-data run**
4. **metrics**
5. **limitations**
6. **promotion / product decision**

Rules:
- final-test evidence is for confirmation, not rule selection;
- no random split for temporal forecasting;
- no automatic model promotion;
- no causal claims unless identified;
- no physical-capacity claim without capacity data;
- preserve source lineage / artifact SHA / scientific identity;
- generated outputs remain under ignored artifact directories.

---

## 2. Architecture / experiment foundation

### 6A — Architecture Baseline
Status: **CLOSED**

Evidence:
- repository architecture/ADR documents under `docs/`;
- OpenAPI snapshot/contract;
- audit/CI gates;
- deterministic TypeScript generation.

Key contract:
`Pydantic → OpenAPI → generated TS → frontend adapters`

### 6B.1 / 6B.1b / 6B.1c
Status: **CLOSED**

Evidence:
- ML manifests;
- scientific/data/config/code identities;
- artifact SHA256;
- checkpoint/resume;
- lock/fencing;
- resource profiles;
- PostgreSQL lineage;
- Alembic migration tests;
- human-controlled promotion.

---

## 3. Patient Journey

Capability:
individual referral time-to-event / event-probability support.

Status: **CLOSED**

Accepted evidence:
full eligible cohort = 767,084 referrals.

### XGBoost AFT
- mean Brier@7/14/30: 0.109753
- C-index: 0.847552
- mean calibration error: 0.009750

### Discrete hospitalization hazard
- mean Brier@7/14/30: 0.108575
- C-index: 0.802645
- mean calibration error: 0.010725

Decision:
retain both; no auto champion.

### Refusal LightGBM
- ROC-AUC: 0.782074
- PR-AUC: 0.364998
- Brier: 0.083447
- calibration error: 0.003399

### Competing risk
Decision:
empirical competing-risk baseline retained; ML challenger rejected.

Known accepted commit:
`a5eb2e9 feat(ml): complete patient journey full-cohort confirmation`

Important contract:
- `estimand_id`;
- hospitalization probabilities 7/14/30;
- optional refusal/unresolved only when actually modeled;
- do not synthesize unresolved from hospitalization-only probability;
- independent marginal models do not imply a coherent joint distribution.

Limitations:
- cohort defined by Q1 2025 registrations;
- serving contract still needs synthesis with the rest of 6B.2.

---

## 4. Flow Forecast deterministic evidence

Capability:
daily hospital/profile flow forecasting.

Status: **CLOSED**

Primary target:
`registrations`

Secondary:
`cohort_hospitalizations`

Accepted run:
`flow-evidence-6b2b1-corrected-v3`

Temporal protocol:
- validation: 2025-02-16, 2025-02-23, 2025-03-02
- final origin: 2025-03-17
- horizons: 1–14

Key result:
recent seasonal average strongest in 5/6 main validation cells.

Decision:
Poisson LightGBM not promoted as universal replacement.

Limitation:
registration history = 90 days only.

---

## 5. Quantile forecast

Capability:
p10 / p50 / p90 probabilistic forecast.

Status: **CLOSED**

Code/config:
- `ml/configs/flow_quantile.yaml`
- `ml/hqai_ml/flow_forecast/quantile.py`
- `ml/pipelines/flow_quantile.py`
- `ml/tests/test_flow_quantile.py`

Documentation:
- `docs/flow-quantile-forecast.md`

Accepted run:
`flow-quantile-6b2b2-real-v1`

Key validation result, registrations/hospital-profile/raw:
- seasonal probabilistic baseline pinball ~0.34558
- quantile LightGBM pinball ~0.28328
- baseline WIS80 ~0.69116
- quantile LightGBM WIS80 ~0.56655

Decision:
`both_retained`

Important:
raw q10/q50/q90 are preserved.

Limitation:
raw interval coverage is not close enough to nominal 80%, especially on final period.

---

## 6. Temporal calibration

Capability:
versioned calibrated uncertainty interval.

Status: **CLOSED**

Accepted run:
`flow-calibration-6b2b2b-real-v1`

Method:
conformal-style symmetric interval expansion on origin-legal residual evidence.

Outputs:
- raw quantiles unchanged;
- calibrated lower/upper stored separately;
- support class and calibration version explicit.

Hospital registrations coverage:
- validation ~50.9% → ~82.97%
- final ~29.9% → ~69.92%

Final date classes:
- weekday ~75.1%
- holiday ~66.7%
- weekend ~59.7%

Decision:
use calibrated “Uncertainty range”; do not promise perfect 80%.

---

## 7. Hierarchical coherence

Capability:
hospital → region → national central consistency.

Status: **CLOSED**

Accepted run:
`flow-hierarchy-6b2b3-real-v1`

Compared:
- current direct;
- bottom-up hospital;
- parent-consistent scaling.

Selected:
`bottom_up_hospital`

Properties:
- hospital child rows unchanged;
- region/national derived by summation;
- exact central coherence;
- no probabilistic reconciliation claim.

This run is the accepted forecast source for pressure warnings.

---

## 8. Preventive Flow Pressure

Capability:
future historical-flow pressure warnings.

Status: **CLOSED**

Code/config:
- `ml/configs/flow_pressure.yaml`
- `ml/hqai_ml/flow_forecast/pressure.py`
- `ml/pipelines/flow_pressure.py`
- `ml/tests/test_flow_pressure.py`

Documentation:
- `docs/flow-pressure-warning.md`

Accepted run:
`flow-pressure-6b2c1-real-v2`

Threshold:
- q90;
- `higher`;
- 56-day origin-legal history;
- hospital/date-class → hospital pooled → region/date-class → region pooled → unsupported.

Severity:
- NORMAL
- WATCH
- ELEVATED
- HIGH
- UNSUPPORTED

Semantics:
`historical_flow_proxy_v1`

Future compatible provider:
`physical_capacity_provider_v1`

Retrospective entity/origin registrations signal usefulness:
- final 14d precision ~39%
- final 14d recall ~68%
- final 7d recall ~66%

Decision:
acceptable as human-reviewed early-warning triage.

Limitation:
not physical-capacity overload.

---

## 9. Observed unusual-flow anomaly

Capability:
detect unusual observed flow now.

Status: **CLOSED as part of 6B.2C-1**

Method:
weekly residual + robust median/MAD.

Signal type:
`observed_unusual_flow`

Rule:
does not change preventive pressure severity.

No causal claim.

---

## 10. Signal Prioritization & Explanation

Capability:
operator-facing Signals Inbox.

Status: **CLOSED**

Code/config:
- `ml/configs/signal_prioritization.yaml`
- `ml/hqai_ml/flow_forecast/prioritization.py`
- `ml/pipelines/signal_prioritization.py`
- `ml/tests/test_signal_prioritization.py`

Documentation:
- `docs/signal-prioritization.md`

Accepted run:
`signal-prioritization-6b2c2-real-v2`

Canonical unit:
`hospital/profile/target/origin`

Ranking:
fixed lexicographic; no learned ranker; no weighted score.

Order:
1. severity
2. shorter lead
3. direct/supported
4. calibrated uncertainty
5. valid central/threshold ratio
6. stable IDs

Explanation:
- headline
- concise reason
- reason codes
- evidence facts

### Product materiality

Fixed rule:
`materiality_floor_expected_count = 1.0`

Supported zero-threshold rows with central forecast <1:
- source severity preserved;
- removed from primary Inbox;
- moved to `zero_baseline_low_volume_attention`.

This is product triage, not model recalibration.

Accepted v2:
- primary Inbox: 7,253
- zero-baseline low-volume attention: 4,081
- unsupported data quality: 502
- observed anomalies: 509
- fallback attention: 2,684
- operationally material HIGH: 4

Primary composition:
- direct-supported: 4,569 (~63%)
- fallback/limited: 2,684 (~37%)

Final-test Top-20:
- 18 direct
- 2 fallback

Runtime:
~7.1 s

Peak memory:
~515 MiB

Decision:
accepted for future Control Tower / Signals Inbox integration.

---

## 11. Data evidence

### Dataset 1
Role:
core referrals / outcomes.

Registration span:
2025-01-01 through 2025-03-31.

Important:
outcomes extend later than the registration window.

### Dataset 2
Role:
same cohort / code dictionary; not an independent live queue feed.

### Dataset 3
Role:
separate receiving-department refusal/load stream.

### Dataset 4
Role:
static ERSB organization snapshot.

Known gap:
no real treated-case time series.

### Dataset 5
Status:
downloaded locally, 105 CSVs.

Current use:
**not integrated**

Required before use:
inventory + joinability + leakage + temporal-density audit + ablation.

### Datasets 6–8
Current use:
not core / not integrated.

---

## 12. Open customer evidence gaps

Still unresolved:
- production user / owner;
- process KPI;
- baseline / target;
- stable IDs;
- source of truth;
- integration mode;
- refresh SLA;
- physical capacity data;
- closed contour;
- SSO / IdP;
- roles / retention;
- deployment target;
- hardware budget;
- support owner.

Do not fill these gaps by assumption.

---

## 13. Current authoritative run chain

Use this chain for downstream reasoning:

`flow-evidence-6b2b1-corrected-v3`
→ `flow-quantile-6b2b2-real-v1`
→ `flow-calibration-6b2b2b-real-v1`
→ `flow-hierarchy-6b2b3-real-v1`
→ `flow-pressure-6b2c1-real-v2`
→ `signal-prioritization-6b2c2-real-v2`
→ `flow-scenario-6b3-real-v1`
→ `decision-alternatives-6b4-real-v3`

Do not cite older superseded pressure/prioritization runs as authoritative evidence.

---

## 14. Constrained Decision Alternatives Engine v1

**6B.4 — Constrained Decision Alternatives Engine v1**
(previously listed as "Constrained Optimizer / Decision Alternatives")

Status: **CLOSED** (spec accepted 2026-09-20; real-data evidence accepted 2026-09-22)

Prerequisite stages 6B.2D (serving contract) and 6B.3 (Forecast Stress-Test Engine v1, section 15)
are CLOSED.

Specification evidence:
- `docs/decision-alternatives-6b4.md` (normative v1 specification, **accepted**)
- `docs/adr/0006-exact-constrained-decision-alternatives.md` (status **Accepted**)

Accepted specification:
- exact one-donor/one-receiver scalar transfer-fraction (`phi`) formulation, same profile, same origin;
- decision basis `CENTRAL_CASE`, with a mandatory non-probabilistic sensitivity-range companion;
- exact closed-form donor minimum and receiver breakpoint semantics, algebraic minimum with safe upward
  binary64 certification;
- no solver dependency;
- full 6B.3 scenario verification required before any alternative is published;
- human review required on every output;
- physical feasibility unknown (`feasibility_status = NOT_PHYSICAL_CAPACITY_VALIDATED`).

Specified capability:
human-reviewed exact constrained decision alternatives over the accepted 6B.3 scenario surrogate —
one scalar same-profile transfer fraction per donor/receiver pair, minimizing total synthetic expected
registrations moved, under a donor `CENTRAL_EXCEEDANCE_CLEARED` goal and a receiver
`NO_WORSE_HISTORICAL_FLOW_PROXY_STATE` constraint, solved by exact breakpoint enumeration with no solver
dependency.

Implemented runtime evidence:
- `ml/hqai_ml/flow_forecast/decision_alternatives.py`;
- `ml/pipelines/decision_alternatives.py`;
- `ml/configs/decision_alternatives.yaml`;
- `ml/tests/test_decision_alternatives.py`;
- `docs/decision-alternatives-implementation.md`.

Accepted run:
`decision-alternatives-6b4-real-v3`

Scientific identity:
`fb7410fa230d4c252c58cbbe98e4ccfbe45102800d5422ba45f8ce79d788a7a8`

Acceptance verdict:
**ACCEPT WITH P2 ONLY** (P0: none; P1: none)

Core acceptance evidence:

- 115 donor units and 460 alternative sets;
- zero full-verification failures, zero receiver worsening, and 100% full-verification success;
- primary `DIRECT_SUPPORTED + COMPLETE`: 29/80 (36.25%) at budget 0.25 and 46/80 (57.5%) at budget 1.00;
- 256 unique full verifications and 174 cache reuses;
- runtime approximately 24,059 seconds; peak RSS 2154.34375 MiB.

Non-blocking P2s:

- laptop runtime was approximately 6.7 hours;
- peak RSS was slightly above the nominal 2 GiB memory budget;
- shortlist-bound drops were 4 alternatives at budget 0.25 and 6 at budget 1.00.

Failed evidence history is preserved and is not accepted evidence:

- `decision-alternatives-6b4-real-v1` — **FAILED EVIDENCE**: real parquet `reason_codes` materialized array-like,
  making boolean truthiness ambiguous;
- `decision-alternatives-6b4-real-v2` — **FAILED EVIDENCE**: raw `float.hex()` containing `+` was embedded in
  `ScenarioSpec.scenario_id` and violated the identifier contract.

The closed capability is retrospective mathematical decision alternatives for human review. Every output uses
`execution_mode = EVALUATION`, `autonomous_action = false`, `human_review_required = true`,
`capacity_checked = false`, `causal_effect_claimed = false`, and `serving_claim = false`; physical feasibility is
not validated, and neither model-registry nor automatic promotion occurs.

Next and final ML stage: **6B.5 — Model Assurance**. Successful 6B.5 closure leads to
**ML CORE CLOSED / ML FREEZE**.

### 6B.2D — synthesis / serving contract

Status: **CLOSED**

Specification evidence:
- `docs/serving-contract-6b2d.md`
- accepted ADR `docs/adr/0005-candidate-independent-intelligence-serving-semantics.md`

Accepted result:
- candidate-independent semantic serving contract and canonical grains;
- explicit Patient Journey estimands and flow uncertainty/hierarchy separation;
- distinct pressure, anomaly, materiality, and Inbox semantics;
- support, fallback, freshness, and provenance rules;
- explicit boundary between retrospective evaluation evidence and future serving execution;
- no database, backend, frontend, or legal-origin runtime serving integration yet.

After:
- 6B.3 Forecast Stress-Test Engine v1 (CLOSED, section 15)
- 6B.4 Constrained Decision Alternatives Engine v1 (CLOSED, section 14)
- 6B.5 Model Assurance (**NEXT / final ML stage**; successful closure leads to **ML CORE CLOSED / ML FREEZE**)

---

## 15. Forecast Stress-Test / Scenario Engine

### 6B.3
Status: **CLOSED**

Accepted run:
`flow-scenario-6b3-real-v1`

Implementation commit:
`36e83f26b8d1e0c5e7a53ec74e102c9d24d4103f`

Scientific identity:
`483dd631ce27d02e351db5b8b8f1e7ac0325bf789c9f35daf897560dbcf51098`

Acceptance verdict:
**ACCEPT WITH P2 ONLY** (P0: none; P1: none)

Accepted capability:
Forecast Stress-Test Engine v1: deterministic non-causal registrations stress testing propagated
through exact central hierarchy, historical-flow pressure, materiality, and prioritization.

Code/config:
- `ml/configs/flow_scenario.yaml`
- `ml/hqai_ml/flow_forecast/scenario.py`
- `ml/pipelines/flow_scenario.py`
- `ml/tests/test_flow_scenario.py`

Documentation:
- `docs/flow-scenario-engine.md`

Accepted source chain:
`flow-hierarchy-6b2b3-real-v1`
→ `flow-pressure-6b2c1-real-v2`
→ `signal-prioritization-6b2c2-real-v2`

Restricted scope:
- deterministic, explicitly synthetic registration stress tests only;
- exactly one reviewed lever per scenario; ordered `composite` sequences are unsupported in v1;
- hospital-level transformation followed by exact bottom-up central aggregation;
- existing historical-flow pressure, entity aggregation, fixed materiality, and lexicographic Inbox rules;
- retrospective `EVALUATION` mode, with no serving claim.

Reporting and vocabulary:
- summaries are per target, with `registrations` primary and `cohort_hospitalizations` reported
  separately as unchanged secondary context, so cohort rows never dilute the registrations denominator;
- derived scenario bounds are published as `scenario_sensitivity_lower/upper` under
  `additive_central_shift_v1`, never under accepted calibrated field names, with no coverage guarantee;
- accepted calibrated evidence stays under `baseline_*` names and is unchanged, as do raw quantiles;
- reason codes preserve the accepted source reason; a severity label is never a reason code.

Standard evidence suite (fixed in configuration before the run):
- baseline identity;
- national registrations ×0.90, ×1.10, and ×1.20.

Accepted real-data results (`registrations`, hospital/profile level):
- baseline reproduction **PASS** at tolerance `1e-9`: 732,144 daily rows, 52,296 entity rows,
  7,253 Inbox rows, 4,081 low-volume rows, 502 unsupported rows;
- identity: 0 daily and 0 entity severity changes; Inbox 7,253 → 7,253; entered 0; left 0;
- ×0.90: 6,320 daily changes (share 0.0173); 1,085 entity changes (share 0.0415);
  Inbox 7,253 → 6,409; entered 0; left 844; 0 upward severity transitions;
- ×1.10: 30,392 daily changes (share 0.0830); 3,194 entity changes (share 0.1222);
  Inbox 7,253 → 8,073; entered 821; left 1; 0 downward severity transitions;
- ×1.20: 37,695 daily changes (share 0.1030); 4,360 entity changes (share 0.1667);
  Inbox 7,253 → 8,845; entered 1,593; left 1; 0 downward severity transitions;
- every scenario: region and national hierarchy error 0 (exact central sums), source frames
  unchanged, raw quantiles untouched, `cohort_hospitalizations` unchanged, counterfactual
  validation false, coverage guarantee false, no promotion, no serving claim, human review required;
- runtime 1,803.5 s; peak memory 3,562.6 MiB (laptop profile).

Acceptance gate:
- the no-op scenario must reproduce accepted daily central/sensitivity bounds/severity/source reason,
  entity severity/crossing/alert flags/severity evidence, and Inbox materiality, eligibility, support
  class and deterministic rank, at tolerance `1e-9`, before any nonzero scenario is accepted;
- scenario scientific identity excludes audit-only specification timestamps;
- the gate passed on real data and the independent acceptance review returned ACCEPT WITH P2 ONLY.

P2 interpretation limitations (non-blocking; see `docs/flow-scenario-engine.md`):
- machine-facing `reason_codes` retain accepted source tokens such as
  `CALIBRATED_LOWER/UPPER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD` even when severity was recomputed from
  scenario sensitivity bounds; they are historical source vocabulary, not evidence that scenario
  bounds were calibrated;
- under positive stress, ELEVATED→HIGH transitions are dominated by zero-threshold sparse cells
  (×1.10: 23,608 of 23,609 daily transitions); the materiality rule keeps them out of the primary
  Inbox, and they must not be read as physical overload;
- the built-in monotonicity validator checks the sign of the central delta; severity transition
  direction was confirmed independently by the acceptance review;
- scope-invariance changed-cell counts use tolerance `1e-9`; the meaningful invariant
  `unexpected_changed_cells = 0` passed;
- `deterministic_synthetic_inputs` means the stress specifications are deterministic and synthetic,
  not that the observed or forecast data are synthetic;
- the summary checkpoint does not repeat the Git commit; clean-tree lineage is authoritative from the
  evaluation manifest and experiment run record, linked to the summary by content hash;
- peak RSS exceeded the nominal 2 GiB laptop budget; this did not affect correctness or completion.

Prohibited claims/outputs:
- no queue or backlog trajectory;
- no capacity, occupancy, bed, or staffing simulation;
- no Monte Carlo or joint predictive probability;
- no causal rerouting, policy counterfactual, or intervention benefit claim;
- no registration-shock propagation into `cohort_hospitalizations`.

This stage is CLOSED as non-causal scenario stress testing. It is not a Digital Twin, causal
intervention model, queue or backlog predictor, or physical-capacity simulator. It does not promote a
model or implement persistence, API, UI, or live scoring.

The authoritative chain continues through the closed
`decision-alternatives-6b4-real-v3` evidence in section 14. Next and final ML stage:
**6B.5 — Model Assurance**; successful closure leads to **ML CORE CLOSED / ML FREEZE**.
