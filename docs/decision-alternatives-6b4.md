# Constrained Decision Alternatives Engine

Step 6B.4 — v1 normative specification

Status: **IMPLEMENTED / REAL-DATA ACCEPTANCE PENDING**
Accepted: 2026-09-20
Optimizer contract version: `constrained-decision-alternatives-v1`
Decision record: [`adr/0006-exact-constrained-decision-alternatives.md`](adr/0006-exact-constrained-decision-alternatives.md) (Accepted)

Acceptance basis: independent science/architecture audit, corrective specification passes, final targeted review
PASS, all known P0/P1 findings resolved. Acceptance of this specification does not mean the optimizer runtime,
real-data acceptance, backend/API integration, or operational feasibility exists.

The contained offline ML runtime is implemented and covered by unit/fixture integration tests. No accepted real-data
6B.4 run or measured result exists yet. No backend, frontend, database, migration, serving, or accepted 6B.3/6B.2C
science is changed. This document fixed the science, contract, and acceptance protocol before implementation.

---

## 1. Normative language and scope

`MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, and `MAY` are normative.

This specification owns the mathematical problem, the constraint taxonomy, the output semantics, the abstention
semantics, and the acceptance protocol of one capability:

> **Constrained Decision Alternatives Engine v1** — generation of human-reviewed, exactly computed mathematical
> alternatives over the accepted 6B.3 scenario surrogate.

It does **not** define endpoints, Pydantic classes, database tables, migrations, UI behaviour, a publication
cadence, a freshness SLA, or an operational approval workflow.

### 1.1 The capability name is normative

The capability is called **Constrained Decision Alternatives Engine**. The following names MUST NOT be used for it,
in code, configuration, artifacts, documentation, commit messages, or operator-facing text:

- AI recommender, recommendation engine;
- routing optimizer, patient router, autonomous routing;
- capacity optimizer, capacity planner;
- Digital Twin, policy simulator, intervention engine.

The single required contract key `optimizer_contract_version` (section 15) keeps its literal name for contract
stability with the accepted `*_contract_version` convention. The field name is a schema key, not a capability
claim, and MUST NOT be quoted as evidence that an optimizer in the operational sense exists.

### 1.2 What v1 actually is

v1 answers exactly one restricted question, for one reviewed signal at a time:

> Under the accepted scenario surrogate, what is the smallest synthetic same-profile transfer fraction that removes
> this donor signal's central threshold exceedance, and which same-profile peer series in the same region can carry
> that synthetic flow without any modelled worsening of their own historical-flow proxy state?

It does not answer whether transferring anything is possible, permitted, safe, clinically appropriate, or
beneficial. Every returned object is a mathematical alternative under explicitly stated constraints, for human
review, in retrospective `EVALUATION` mode.

---

## 2. Accepted inputs and lineage

v1 is built strictly on top of accepted, closed evidence. It introduces no new forecast, no new threshold, no new
calibration, no new severity rule, and no new ranking rule.

```text
flow-evidence-6b2b1-corrected-v3
  → flow-quantile-6b2b2-real-v1
  → flow-calibration-6b2b2b-real-v1
  → flow-hierarchy-6b2b3-real-v1
  → flow-pressure-6b2c1-real-v2
  → signal-prioritization-6b2c2-real-v2
  → flow-scenario-6b3-real-v1        (Forecast Stress-Test Engine v1, CLOSED)
```

Normative reading dependencies:

- [`flow-scenario-engine.md`](flow-scenario-engine.md) — the accepted scenario surrogate, its `inflow_transfer`
  lever, the `additive_central_shift_v1` sensitivity transform, the identity gate, and its P2 limitations;
- [`flow-pressure-warning.md`](flow-pressure-warning.md) — `historical_flow_proxy_v1` thresholds and the severity
  rule;
- [`signal-prioritization.md`](signal-prioritization.md) — the Signals Inbox, the fixed materiality floor, and the
  lexicographic ranking contract;
- [`serving-contract-6b2d.md`](serving-contract-6b2d.md) — candidate-independent serving semantics, the
  evaluation/serving boundary, and the forbidden-interpretation list;
- [`adr/0005-candidate-independent-intelligence-serving-semantics.md`](adr/0005-candidate-independent-intelligence-serving-semantics.md).

### 2.1 The accepted transfer lever already exists

The 6B.3 engine already implements the exact transform v1 needs, as the reviewed `inflow_transfer` lever with
classification `MECHANISTIC_ACCOUNTING_SCENARIO`. **v1 therefore requires no new lever, no new scenario
classification, and no change to any accepted 6B.3 code path.** 6B.4 is a *search and constraint* layer that
selects lever parameters and verifies the result through the unchanged accepted engine.

Any proposal that would require editing `ml/hqai_ml/flow_forecast/scenario.py`, `pressure.py`, or
`prioritization.py` is out of v1 scope by definition and requires its own review.

---

## 3. Canonical unit

One optimization problem — the **canonical unit** — is:

```text
one accepted forecast origin
  × target = REGISTRATIONS
  × one profile
  × one selected donor hospital/profile signal
  × the candidate set of same-profile receiver hospitals
```

Identity of a canonical unit:

`(optimizer_contract_version, origin, target, profile_id, donor_hospital_id, donor_goal,
search_policy_identity, constraint_policy_identity)`

Rules:

- there is **no patient-level decision unit**; no object in v1 refers to a patient, a referral, an individual
  transfer, a bed, or a person;
- one canonical unit produces exactly one `DecisionAlternativeSet`;
- alternatives from different canonical units MUST NOT be pooled, compared, Pareto-filtered together, or ranked
  against each other;
- the target is `REGISTRATIONS` only. `cohort_hospitalizations` is never a decision target and is never modified.

---

## 4. Decision variable and the exact transform

### 4.1 Notation

Fix an origin `o`, target `REGISTRATIONS`, profile `p`, donor hospital `i`, receiver hospital `j`, and horizons
`t = 1 … 14` with target dates `d(t) = o + t` days.

From the accepted daily pressure evidence, for a hospital `h` and horizon `t`:

| symbol | accepted source field | meaning |
|---|---|---|
| `c_h(t)` | `forecast_value` (baseline central) | accepted central expected registrations, a continuous expected count `≥ 0` |
| `L_h(t)` | `uncertainty_lower` (level-local calibrated) | accepted calibrated lower bound, usable only when `uncertainty_status = level_local_calibrated` and both bounds are finite |
| `U_h(t)` | `uncertainty_upper` (level-local calibrated) | accepted calibrated upper bound, same usability rule |
| `T_h(t)` | `threshold_value` | accepted origin-legal `historical_flow_proxy_v1` threshold for the target date's date class |
| `S_h(t)` | `threshold_status` | `supported` or `unsupported` |

`R_h(t) ∈ {USABLE, UNAVAILABLE}` denotes accepted range usability at that cell. `R_h(t) = UNAVAILABLE` means the
accepted forecast evidence carries no usable calibrated range; it is not a model failure, not a capacity fact, and
not a confidence score.

### 4.2 The decision variable

For one donor `i` and one receiver `j`:

```text
phi ∈ [0, 1]
```

`phi` is **one scalar transfer fraction applied to every horizon `t = 1 … 14` of the donor series**. There is no
per-horizon variable, no per-day schedule, and no vector decision in v1.

### 4.3 The transform (identical to the accepted 6B.3 lever)

For every `t = 1 … 14`:

```text
moved(t)  = phi * c_i(t)

donor:     c'_i(t) = (1 - phi) * c_i(t)
receiver:  c'_j(t) = c_j(t) + phi * c_i(t)
```

Derived central deltas:

```text
delta_i(t) = -phi * c_i(t)  ≤ 0
delta_j(t) = +phi * c_i(t)  ≥ 0
```

Scenario sensitivity range, reusing the accepted `additive_central_shift_v1` transform unchanged, for any hospital
`h` with `R_h(t) = USABLE`:

```text
L'_h(t) = max(0, L_h(t) + delta_h(t))
U'_h(t) = max(L'_h(t), U_h(t) + delta_h(t))
```

When `R_h(t) = UNAVAILABLE`, `L'_h(t)` and `U'_h(t)` are undefined (`NaN`), the scenario range status is
`UNAVAILABLE`, and the cell carries `SCENARIO_SENSITIVITY_RANGE_UNAVAILABLE`. Missing range evidence MUST NOT
create `WATCH` or `HIGH`, and MUST NOT be substituted, imputed, or defaulted.

Rules:

- the transform is **same profile only**: `p` is identical for donor and receiver, and no cross-profile transfer is
  representable in v1;
- the transform is **same origin and same target date only**: `moved(t)` leaves donor cell `(i, o, d(t))` and
  enters receiver cell `(j, o, d(t))`; no time shifting, no redistribution across horizons;
- expected registrations are **continuous expected counts**. `phi` MUST NOT be discretized into patient counts,
  rounded to integers, or described as a number of patients;
- the affected horizon set is `A = { t : c_i(t) > 0 }`. For `t ∉ A`, `moved(t) = 0` and every donor and receiver
  field at `t` is bit-identical to baseline;
- `phi = 0` reproduces the baseline exactly (invariant 1, section 20).

---

## 5. Primary objective

```text
minimize   phi * Σ_{t=1..14} c_i(t)
```

This is **total synthetic expected registrations moved**, published as
`transferred_expected_registrations_total`.

Because `Σ_t c_i(t) > 0` for every eligible donor (section 7 requires at least one central exceedance, which
requires `c_i(t) > T_i(t) ≥ 0`), the objective is a strictly increasing linear function of `phi`. Minimizing the
objective is therefore identical to minimizing `phi`.

The objective MUST NOT be, contain, or be traded against:

- a severity score, a weighted severity index, or a count of `HIGH` rows;
- an Inbox count, an Inbox rank, or a rank improvement;
- waiting time, queue length, backlog, or clearance time;
- refusals, refusal probability, or refusal load;
- any clinical outcome, benefit, or utility;
- any learned score, any weighted "AI score", or any scalarized composite.

Warning counts and severity states are **diagnostics or hard constraints, never weighted utility terms**. There is
no hidden scalar score anywhere in v1 (invariant 17, section 20).

---

## 6. Donor eligibility and the donor goal

### 6.1 Primary donor population

A donor signal is eligible for the **primary donor forecast-support tier** if and only if every condition holds,
evaluated on the
accepted `signal-prioritization-6b2c2-real-v2` artifacts without recomputation:

1. `target = registrations`;
2. it is a **primary Inbox** row: `operational_priority_status = primary_inbox_eligible`. Rows in
   `zero_baseline_low_volume_attention` or `unsupported_data_quality` are excluded;
3. `threshold_status = supported` on the entity's severity evidence cell;
4. it is **central-driven**: the binding set `B_i` (section 6.2) is non-empty;
5. displayed severity `∈ {ELEVATED, HIGH}`;
6. `priority_support_class = direct_supported`.

Donors satisfying 1–5 but with `priority_support_class = fallback_or_limited_history` MAY be evaluated **only** in a
separately labelled lower-evidence tier (`FALLBACK_LIMITED`, section 14). Their results MUST NOT be pooled with
primary-tier results in any metric.

Donors with `threshold_status = unsupported` on the entity severity-evidence cell are forbidden. Binding cells are
supported by definition because `S_i(t) = supported` is part of `B_i`. Unsupported **non-binding** donor horizons
may remain in the 14-day series; they remain explicitly `UNSUPPORTED`, are never reinterpreted as safe evidence,
and are not subject to `CENTRAL_EXCEEDANCE_CLEARED`, which applies only to `B_i`. v1 does not require all 14 donor
horizons to be threshold-supported unless a future reviewed policy says so.

### 6.2 The binding set and the central-driven requirement

```text
B_i = { t ∈ [1, 14] : S_i(t) = supported  and  c_i(t) > T_i(t) }
```

`B_i` is the set of donor horizon cells whose **central** forecast strictly exceeds the accepted historical-flow
threshold. `B_i` is the binding set of the donor goal.

- `B_i = ∅` means the donor is **not central-driven**. Such a signal MUST NOT be an optimizer target, and the unit
  abstains with `DONOR_NOT_CENTRAL_DRIVEN`.
- A `WATCH`-only signal necessarily has `B_i = ∅` (`WATCH` fires only from the upper bound). **WATCH-only donor
  optimization is forbidden** (invariant 23, section 20).
- A `HIGH` signal whose severity is produced only by the lower bound (`L_i(t) > T_i(t)` while `c_i(t) ≤ T_i(t)`
  everywhere) also has `B_i = ∅` and is likewise **not** an eligible target. Range-driven severity is not a central
  exceedance and v1 has no goal for it.

### 6.3 The donor goal

```text
CENTRAL_EXCEEDANCE_CLEARED
```

Definition, and the only donor goal in v1:

> For every binding donor cell `t ∈ B_i`, the scenario central no longer exceeds the accepted historical-flow
> threshold: `c'_i(t) ≤ T_i(t)`.

The goal is stated on the **central case only**. v1 does not optimize `WATCH` relief, does not optimize range-driven
`HIGH`, and does not optimize any severity label directly.

### 6.4 What the donor goal does not mean — mandatory non-claims

These are normative non-claims. Each MUST appear in the deterministic explanation of any alternative it applies to.

1. **Clearing central exceedance does not imply the donor cell leaves `HIGH`.** `HIGH` fires when
   `L'_i(t) > T_i(t)`. Per the accepted serving contract, a level-local calibrated interval need not contain the
   hierarchy-adjusted central forecast, so `L_i(t) > T_i(t)` is possible while `c_i(t) > T_i(t)` as well. At the
   minimum fraction, `c'_i(t) = T_i(t)` exactly, and `L'_i(t) = max(0, L_i(t) - phi·c_i(t))` may still exceed
   `T_i(t)`. The alternative MUST publish `scenario_donor_state` and the diagnostic
   `donor_residual_range_driven_high_horizons`.
2. **Clearing central exceedance does not imply the donor becomes `NORMAL`.** The donor may become `WATCH`
   (`U'_i(t) > T_i(t)`).
3. **Clearing central exceedance does not imply the donor leaves the primary Inbox.** Inbox membership depends on
   the entity displayed severity, the fixed materiality rule, and the accepted lexicographic ranking over the whole
   ranking partition. That is established only by full 6B.3 verification (section 13) and is `null` before it.
4. **No causal, operational, or clinical improvement is claimed for the donor.** Nothing is prevented, reduced,
   avoided, or improved.

### 6.5 Donor severity can never worsen — derived property, not an assumption

**Lemma L1 (donor monotonicity).** For a fixed donor cell, `c'_i(t)`, `L'_i(t)`, and `U'_i(t)` are all
non-increasing in `phi`, and `S_i(t)` is invariant. By Lemma L3 (section 11.2) the cell's severity rank is therefore
non-increasing in `phi`.

Consequence: the transform can never worsen a donor cell, so v1 needs no donor-side no-worse constraint. The
implementation MUST still assert this (invariant 6 and the certified re-check of section 11.5) rather than rely on
the proof.

---

## 7. Receiver eligibility

A hospital `j` is a **v1 receiver candidate** for donor `i` at `(o, REGISTRATIONS, p)` if and only if:

1. `j ≠ i`;
2. same profile `p`;
3. same region as `i` — an explicit **product policy** for v1, not a scientific fact (section 9.2);
4. same origin `o` and target `REGISTRATIONS`;
5. **supported threshold evidence on every affected horizon**: `S_j(t) = supported` for all `t ∈ A`. A single
   unsupported affected cell rejects the receiver, because an unsupported cell cannot be evaluated for harm and
   unsupported evidence is never treated as safe;
6. **aligned complete cell set**: `j` has exactly one registrations cell for each `t = 1 … 14` at origin `o` and
   profile `p`, with target dates aligned to the donor's, and no duplicate cells. This mirrors the accepted engine's
   `INVALID_TRANSFER_ALIGNMENT` contract and is required for full verification to be runnable at all;
7. `j` is in `eligible_receiver_ids` when that user constraint is supplied (section 9.3).

`priority_support_class` is **not** an eligibility condition for a receiver; it maps to the forecast-support tier
(section 14). Receivers with `threshold_status = unsupported` anywhere in `A` are rejected — **unsupported
receivers are rejected**, never scored, never displayed as marginal.

### 7.1 Mandatory vocabulary for receivers

No receiver may be described, in any field name, value, log line, explanation, document, or commit message, as:

- available, having availability;
- having capacity, having spare capacity, having free beds, having slack;
- able to accept patients, able to take patients;
- able to absorb patients, able to absorb load.

The only approved description of a receiver candidate is:

> **same-profile peer series with modelled headroom under the historical-flow proxy**

"Headroom" in v1 means exactly `T_j(t) - c'_j(t)` under `historical_flow_proxy_v1`. It is a modelled distance to a
historical-flow quantile, not physical capacity and not an operational allowance.

### 7.2 The receiver threshold comparator is an assumption, and MUST be declared

`T_j(t)` was estimated from receiver `j`'s own origin-legal history, which does **not** include the synthetic
transferred flow. Comparing the augmented central series `c'_j(t)` against `T_j(t)` is a synthetic accounting
comparison against an unchanged historical reference. It is not a re-estimated threshold, not a capacity check, and
not evidence that `j` can carry the flow. Every alternative MUST carry the standing limitation code
`THRESHOLD_COMPARATOR_ASSUMPTION` alongside `NOT_PHYSICAL_CAPACITY_VALIDATED`. Thresholds are never re-estimated,
re-fitted, or adjusted by 6B.4 (section 9.1).

---

## 8. The receiver no-worse constraint

### 8.1 Statement

```text
NO_WORSE_HISTORICAL_FLOW_PROXY_STATE
```

For every horizon `t = 1 … 14`:

```text
rank( PressureSeverity_scenario(j, t) )  ≤  rank( PressureSeverity_baseline(j, t) )
```

using the accepted `SEVERITY_RANK` ordering `UNSUPPORTED(-1) < NORMAL(0) < WATCH(1) < ELEVATED(2) < HIGH(3)` and
the accepted 6B.3 scenario sensitivity semantics (`additive_central_shift_v1`) to produce the scenario bounds.

Notes:

- for `t ∉ A` the constraint holds by exact invariance, so it binds only on affected horizons;
- `S_j(t)` is invariant under the transform, so the comparison never crosses the `UNSUPPORTED` boundary; the
  `-1` rank is unreachable as a transition and receiver eligibility already rejects unsupported affected cells;
- the comparison is **per horizon cell**, not on the entity displayed severity. A constraint stated only on the
  14-day maximum would permit worsening on individual days hidden by an unchanged maximum.

### 8.2 What this constraint is not

`NO_WORSE_HISTORICAL_FLOW_PROXY_STATE` is **not**:

- a capacity constraint;
- a bed, staffing, occupancy, or census constraint;
- an operational feasibility proof;
- a safety guarantee;
- evidence that the receiver is unaffected in reality.

It is exactly one statement: under the accepted historical-flow proxy and the accepted scenario surrogate, no
receiver day's modelled severity state is higher than its baseline modelled severity state.

### 8.3 Receiver harm is evaluated on raw scientific severity

Receiver harm MUST be evaluated on the **raw** accepted severity rule, cell by cell. The product materiality floor
(`materiality_floor_expected_count = 1.0`) MUST NOT be applied when evaluating receiver harm. Materiality is
product triage for donor search visibility (section 14); using it on the receiver side would hide real modelled
worsening on low-volume cells behind a product filter.

Consequently a receiver cell may be blocked by the constraint even though the corresponding worsening would never
have appeared in the primary Inbox. That is intended.

---

## 9. Constraint taxonomy

Four classes, kept strictly separate. An implementation MUST record which class rejected or bounded each candidate.

### 9.1 Scientific hard constraints — non-negotiable

These are properties of the accepted evidence. They are not configurable, not relaxable, and not overridable by any
policy, budget, user input, or reviewer.

1. **registrations only** — `cohort_hospitalizations` is never a decision target;
2. **same profile** — donor and receiver profile identical;
3. **same origin** — one accepted forecast origin per canonical unit;
4. **same target date / horizon** — flow leaves and enters the same `(origin, target_date)` cell;
5. **exact flow conservation** — `Σ_t (c'_i(t) + c'_j(t)) = Σ_t (c_i(t) + c_j(t))` within `1e-9`, and per horizon
   `c'_i(t) + c'_j(t) = c_i(t) + c_j(t)` within `1e-9`;
6. **nonnegative donor flow** — `c'_i(t) ≥ 0` for all `t`; `phi ∈ [0,1]` and `c_i(t) ≥ 0` make this structural;
7. **hospital/profile child-level transform only** — the transform is applied to hospital/profile rows before any
   parent aggregation;
8. **exact bottom-up central hierarchy after verification** — region central is the exact sum of hospital central
   and national central the exact sum of regions, with maximum absolute error `0` at tolerance `1e-9`;
9. **no `cohort_hospitalizations` modification** — bit-identical secondary context;
10. **historical thresholds unchanged** — `T_h(t)`, `threshold_status`, `threshold_fallback_level`,
    `threshold_semantics`, and threshold provenance are read-only facts;
11. **support/fallback provenance unchanged** — `support_status`, `fallback_status`, `forecast_source`,
    `uncertainty_status`, `calibration_version`, and raw quantiles are read-only facts; a transformed fallback
    forecast never becomes directly supported;
12. **unsupported evidence cannot be treated as safe** — unsupported thresholds, unavailable ranges, and missing
    cells are never defaulted to zero, normal, safe, certain, or direct.

### 9.2 Product policy constraints

Reviewed product decisions, explicitly not scientific facts. They are recorded in `constraint_policy` with their own
identity and MUST be labelled as policy wherever they appear.

| policy | v1 value | nature |
|---|---|---|
| `receiver_geographic_scope` | `SAME_REGION` | product policy; a placeholder until customer geography/referral rules exist |
| `donor_search_population` | materially eligible primary Inbox only | product triage (section 14) |
| `donor_evidence_tiers` | `DIRECT_SUPPORTED` primary, `FALLBACK_LIMITED` separately labelled | evidence governance |
| `decision_basis` | `CENTRAL_CASE` | reviewed decision policy |

`SAME_REGION` is a v1 simplification chosen because it is the narrowest defensible scope and because it maps onto
the accepted engine's `region_profile` scope (section 13.2). It is **not** evidence that same-region transfer is
permitted, appropriate, or operationally meaningful.

### 9.3 User / product-configurable constraints

Supplied by a reviewer before a run, recorded in `constraint_policy`, never inferred from data.

| constraint | type | meaning |
|---|---|---|
| `max_transfer_fraction` | float in `[0,1]` | **policy budget** cap on `phi` |
| `max_total_synthetic_transfer` | float `≥ 0`, nullable | **policy budget** cap on `phi · Σ_t c_i(t)` |
| `eligible_receiver_ids` | set of hospital ids, nullable | explicit receiver allow-list |
| `geographic_scope` | enum, v1 fixed to `SAME_REGION` | receiver geography rule |

A configurable transfer cap is a **POLICY BUDGET**. It is **NOT** physical capacity, not an operational allowance,
not a measured limit, and not derived from any data. The implementation MUST NOT infer, fit, tune, calibrate, or
learn any of these values from data, from outcomes, or from optimizer results.

### 9.4 Missing-data constraints — absent by necessity

These constraints cannot be expressed in v1 because the required data does not exist in the project. Their absence
MUST be declared on every alternative, never silently treated as satisfied.

- physical capacity, staffed operational capacity, beds;
- occupancy, census, free capacity;
- staffing, rosters, shift patterns;
- hospital service/profile compatibility;
- contractual, referral, or administrative routing permissions;
- transport feasibility, distance, or travel time;
- clinical appropriateness of a transfer;
- refusal-flow response of the receiver.

Standing consequence on every alternative:

```text
feasibility_status  = NOT_PHYSICAL_CAPACITY_VALIDATED
capacity_checked    = false
```

equivalently reported as `PHYSICAL_FEASIBILITY_UNKNOWN`.

---

## 10. Central case and the sensitivity-range companion

### 10.1 Primary decision basis

```text
decision_basis = CENTRAL_CASE
```

The donor goal, the objective, and the minimum fraction are defined on the central case. v1 MUST NOT optimize
`WATCH` relief and MUST NOT target the sensitivity range.

### 10.2 Mandatory companion result

Every candidate — feasible or not — MUST also report `SENSITIVITY_RANGE_CASE`, computed with the accepted 6B.3
transformed scenario sensitivity range (`additive_central_shift_v1`) at the same `phi`:

- the donor's and receiver's per-horizon `scenario_sensitivity_lower/upper` and `scenario_uncertainty_status`;
- `receiver_range_worst_severity_after` — the receiver's worst range-driven state over `A`;
- `sensitivity_range_result`, a three-valued deterministic label:

| value | condition |
|---|---|
| `ROBUST_TO_TRANSFORMED_RANGE` | every affected receiver cell has `R_j(t) = USABLE` **and** `U'_j(t) ≤ T_j(t)` |
| `NOT_ROBUST_TO_TRANSFORMED_RANGE` | every affected receiver cell has `R_j(t) = USABLE` **and** `U'_j(t) > T_j(t)` for at least one |
| `RANGE_EVIDENCE_INCOMPLETE` | at least one affected receiver cell has `R_j(t) = UNAVAILABLE` |

`RANGE_EVIDENCE_INCOMPLETE` MUST NOT be reported, displayed, aggregated, or defaulted as robust. Missing evidence
is not robustness.

### 10.3 Hard limits on interpreting the range

The specification states, and every alternative MUST carry:

- the scenario range is **not recalibrated** (`range_recalibrated = false`);
- it carries **no probability**;
- it carries **no confidence level**;
- it carries **no coverage guarantee** (`coverage_guarantee = false`);
- it is **not a joint distribution** over hospitals, horizons, or profiles.

This MUST NOT be called probabilistic robust optimization, stochastic optimization, robust optimization under
uncertainty, or chance-constrained optimization. `ROBUST_TO_TRANSFORMED_RANGE` is a deterministic label about a
transformed deterministic interval and nothing else.

Inherited 6B.3 P2 caveat: machine-facing reason codes may still read
`CALIBRATED_LOWER/UPPER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD` even where severity was recomputed from scenario
sensitivity bounds. Those tokens are accepted historical source vocabulary. Operator-facing text MUST use the
scenario wording ("Derived scenario sensitivity lower/upper bound"), exactly as the accepted engine already
rewrites it.

### 10.4 Missing range mechanically relaxes the receiver constraint — mandatory disclosure

`HIGH` and `WATCH` cannot fire without a usable range. Therefore a receiver cell with `R_j(t) = UNAVAILABLE`
**cannot be worsened into `WATCH` or `HIGH`**, and the receiver no-worse constraint binds only through the central
predicate there. A receiver with unavailable range evidence will consequently appear to tolerate a larger `phi`
than an otherwise identical receiver with usable range evidence.

This is an artefact of missing evidence, not a property of the receiver. v1 MUST:

- publish `receiver_range_masking_present = true` whenever any affected receiver cell has `R_j(t) = UNAVAILABLE`;
- set `receiver_range_evidence = RANGE_LIMITED`; this axis is independent of forecast support, so the same
  alternative may still have `forecast_support_tier = DIRECT_SUPPORTED`;
- set `sensitivity_range_result = RANGE_EVIDENCE_INCOMPLETE` for that alternative;
- permit the alternative to be published with this disclosure after full verification, but exclude it from the
  primary complete-evidence acceptance cohort;
- report, in the acceptance protocol, the alternative counts and minimum-fraction distributions **split by receiver
  range-evidence tier**, never pooled.

Missing range evidence can mechanically remove `WATCH`/`HIGH` predicates and make the receiver appear more tolerant;
it does not change the provenance of the central forecast. Therefore forecast support and receiver range evidence
are orthogonal axes and MUST NOT be collapsed into one label.

---

## 11. The exact algorithm

```text
algorithm = EXACT_BREAKPOINT_ENUMERATION_V1
```

v1 uses **exact breakpoint enumeration** in closed form. It MUST NOT use, and MUST NOT introduce a dependency on:

- MILP or any mixed-integer solver;
- CP-SAT or any constraint-programming solver;
- LP solvers;
- grid search or parameter sweeps over `phi`;
- greedy or local search;
- evolutionary, annealing, or metaheuristic search;
- gradient-based or black-box optimization;
- any learned policy, surrogate model, or scoring model.

No solver dependency is added to the project by v1.

### 11.1 The accepted severity rule (read-only)

```text
UNSUPPORTED  if threshold unsupported or threshold not finite
HIGH         if sensitivity lower is finite and lower > T
ELEVATED     if central > T
WATCH        if sensitivity upper is finite and upper > T
NORMAL       otherwise
```

Every inequality is **strict**. This rule is accepted 6B.2C-1 science and is reused unchanged.

### 11.2 Three lemmas that make the problem exactly solvable

**Lemma L3 (cascade equals maximum).** The accepted rule returns the highest-ranked satisfied predicate, so for a
supported cell

```text
rank = max( 3·[L' > T],  2·[c' > T],  1·[U' > T],  0 )
```

This is not a simplification: because `L' > T`, `c' > T`, and `U' > T` do not imply one another (a level-local
calibrated interval need not contain the hierarchy-adjusted central forecast), the cascade is genuinely a maximum
over independent predicates.

**Lemma L1 (donor monotonicity).** `c'_i`, `L'_i`, `U'_i` are non-increasing in `phi`; with L3 the donor cell rank
is non-increasing in `phi`.

**Lemma L2 (receiver monotonicity).** `delta_j(t) = phi·c_i(t)` is non-decreasing in `phi`, so `c'_j`,
`L'_j = max(0, L_j + delta_j)`, and `U'_j = max(L'_j, U_j + delta_j)` are non-decreasing in `phi`; with L3 the
receiver cell rank is non-decreasing in `phi`.

**Corollary L4 (closed feasible sets).** Each predicate is a strict inequality on a continuous monotone function of
`phi`, so:

```text
donor goal set                    = [phi_min, 1]     (closed)
receiver no-worse set             = [0, phi_max]     (closed)
```

Both are single closed intervals. The feasible set of the canonical problem for one receiver is their intersection
with the policy budget, again a single closed interval.

### 11.3 Exact donor minimum — closed form

For `t ∈ B_i` we have `c_i(t) > T_i(t) ≥ 0`, hence `c_i(t) > 0`, and

```text
(1 - phi) * c_i(t) ≤ T_i(t)
  ⟺  phi ≥ 1 - T_i(t) / c_i(t)
```

Therefore

```text
phi_min = max over t ∈ B_i of ( 1 - T_i(t) / c_i(t) )        ∈ (0, 1]
```

`phi_min` is the exact algebraic minimum transfer fraction achieving `CENTRAL_EXCEEDANCE_CLEARED`. The `argmax`
cell is the **binding donor cell** and MUST be published. If multiple horizons attain the same binding maximum, the
published binding donor cell is the one with the smallest horizon number.

**Lemma L5 (receiver independence).** `phi_min` depends only on the donor's own cells. It is identical for every
receiver candidate of the canonical unit. Consequently `total_synthetic_flow_moved` is identical across all feasible
alternatives of one canonical unit, and Pareto filtering within a unit discriminates only on the receiver-side
dimensions (section 16.3).

**Zero-threshold binding cells.** If `T_i(t) = 0` for a binding cell, then `1 - T_i(t)/c_i(t) = 1` and
`phi_min = 1.0` exactly: the donor goal requires moving the donor's entire expected registrations for every
horizon. The accepted `historical_flow_proxy_v1` thresholds do contain exactly-zero supported values, and the
product materiality rule is evaluated only on the entity's **severity evidence cell**, so a materially eligible
donor can still have a zero-threshold binding cell at another horizon. The implementation MUST publish
`donor_zero_threshold_binding_present` and MUST NOT special-case, clip, or soften such cells. Section 21 requires
this share to be reported.

### 11.4 Exact receiver breakpoints

For each `t` with `m = c_i(t) > 0` and baseline receiver rank `r = rank_j(t)`, the no-worse constraint forbids any
strictly higher-ranked predicate from becoming satisfied. With `T = T_j(t)`:

| baseline rank `r` | predicates that must stay false | exact upper bounds on `phi` |
|---|---|---|
| `3` HIGH | none | none — the cell can never bind |
| `2` ELEVATED | `L' > T` | `phi ≤ (T − L_j)/m` when `R_j(t) = USABLE` |
| `1` WATCH | `L' > T`, `c' > T` | `phi ≤ (T − L_j)/m` when `USABLE`; `phi ≤ (T − c_j)/m` |
| `0` NORMAL | `L' > T`, `c' > T`, `U' > T` | `phi ≤ (T − L_j)/m` and `phi ≤ (T − U_j)/m` when `USABLE`; `phi ≤ (T − c_j)/m` |

Derivations:

- `L' ≤ T` is `max(0, L_j + phi·m) ≤ T`; since `T ≥ 0` this is exactly `L_j + phi·m ≤ T`;
- `U' ≤ T` is `max(L', U_j + phi·m) ≤ T`, which given `L' ≤ T` is exactly `U_j + phi·m ≤ T`;
- every numerator is `≥ 0` because the corresponding baseline predicate is false at `phi = 0`;
- when `m = 0` the cell imposes no bound, because the cell is bit-identical to baseline;
- when `R_j(t) = UNAVAILABLE` the `L'` and `U'` predicates are permanently false and their bounds are omitted; see
  the mandatory disclosure in section 10.4.

**Zero-threshold receiver cells.** For a baseline `NORMAL` receiver cell with `T = 0`, every positive central
increase satisfies `c'_j > T`, so the central breakpoint is `phi = 0`; the certified `phi_max` may therefore be
exactly zero and the receiver may become `RECEIVER_BLOCKED` immediately. For baseline `ELEVATED` or `HIGH` cells
with `T = 0`, the applicable higher-rank predicates depend on usable scenario sensitivity evidence and the accepted
severity cascade above. If that range evidence is missing, the omitted `L'`/`U'` predicates can make the receiver
bound mechanically more permissive. Such a candidate MUST set `receiver_range_masking_present = true`,
`receiver_range_evidence = RANGE_LIMITED`, and `sensitivity_range_result = RANGE_EVIDENCE_INCOMPLETE`; it is not
primary complete-evidence acceptance.

Then

```text
phi_max = min( 1, min over all applicable breakpoints )
```

with `phi_max = 1` when no breakpoint applies. Breakpoint candidates MUST be enumerated in a deterministic order —
ascending value, ties broken by `(horizon, predicate_rank, receiver_hospital_id)` — so that the identified binding
receiver cell is reproducible. The binding receiver cell and predicate MUST be published.

### 11.5 Selection, upward candidate certification, and numeric determinism

The scientific minimum is the exact algebraic value `phi_min_alg` defined by the formula in section 11.3. Binary64
is only the execution and replay representation of that algebraically defined minimum; it does not redefine the
optimization problem. The implementation computes the formula in its deterministic arithmetic representation and
selects `float(phi_min_alg)` as the initial binary64 candidate.

For the lower-bound comparison, each finite binary64 input `T_i(t)` and `c_i(t)` is interpreted as the exact real
number it encodes. The implementation MUST use exact rational comparison or an equivalent directed-rounding method
to establish `phi ≥ phi_min_alg`; testing only the rounded product `(1 − phi)·c_i(t) ≤ T_i(t)` is insufficient.

Certification is required because the accepted severity predicates use strict `>` comparisons and an algebraic
boundary such as `1 − T/c` may round when represented and substituted into the binary64 calculation. Upward
certification prevents floating-point rounding from publishing a transfer fraction below the mathematically required
boundary. Downward ULP tightening of the chosen donor fraction is forbidden: apparent feasibility caused only by
rounding of `(1 − phi)` does not establish feasibility relative to the exact algebraic optimization problem.

The normative order is:

1. derive algebraic `phi_min_alg` and every algebraic receiver breakpoint, then `phi_max_alg`;
2. certify the donor lower bound upward and receiver/policy upper bounds downward into binary64 values;
3. compare the **certified** donor and receiver bounds—never uncertified algebraic floats;
4. choose the certified donor lower bound as the final candidate when it lies within every certified upper bound;
5. upward-certify the chosen candidate as needed; never move the chosen donor candidate downward;
6. re-check receiver no-worse and every other constraint at the exact final published float.

Receiver breakpoint certification uses `nextafter(bound, 0.0)` until the exact bound satisfies receiver no-worse.
Fraction and total-transfer policy budgets are likewise treated as certified upper bounds. This downward movement is
safe certification of an **upper bound** and is distinct from the forbidden downward movement of the selected donor
fraction. Donor lower-bound certification starts from the binary64 encoding of `phi_min_alg`, advances only with
`nextafter(phi, +infinity)` until every binding donor predicate passes, and accumulates those moves in
`certify_up_steps`. The donor lower-bound test requires both that the candidate is not below `phi_min_alg` under the
deterministic algebraic-bound comparison and that recomputation at the candidate satisfies every binding donor
predicate. Then:

```text
phi_cap = min(phi_max_certified,
              max_transfer_fraction_certified,
              max_total_synthetic_transfer_bound_certified)
```

- if `phi_min_certified > phi_max_certified` → `RECEIVER_BLOCKED`;
- else if `phi_min_certified >` either certified policy-budget bound → `TRANSFER_BUDGET_INSUFFICIENT`;
- otherwise the candidate is `phi_min_certified`. The objective remains strictly increasing and no search is used.

The final upward certification is:

```text
phi = float(phi_min_alg)
certify_up_steps = 0

while true:
    test the current phi against the donor lower-bound certification
    if the donor lower bound passes:
        phi_min_certified = phi
        break
    if certify_up_steps == PHI_GUARD_MAX_STEPS:
        fail PHI_CERTIFICATION_FAILED
    phi = nextafter(phi, +infinity)
    certify_up_steps += 1

compare phi_min_certified with every certified upper bound
if phi_min_certified > phi_max_certified:
    fail RECEIVER_BLOCKED
if phi_min_certified exceeds either certified policy-budget bound:
    fail TRANSFER_BUDGET_INSUFFICIENT

phi = phi_min_certified
while true:
    test final_certification(phi)
    if every required constraint passes:
        break
    if any upper-bound, domain, or conservation constraint fails:
        fail PHI_CERTIFICATION_FAILED          # increasing phi cannot repair it
    if certify_up_steps == PHI_GUARD_MAX_STEPS:
        fail PHI_CERTIFICATION_FAILED
    phi = nextafter(phi, +infinity)
    certify_up_steps += 1

if final_certification(phi) fails:
    fail PHI_CERTIFICATION_FAILED
```

Both loops test the current candidate **before** checking whether the step budget is exhausted. A candidate reached
by the final permitted upward correction is therefore tested and may succeed. `PHI_GUARD_MAX_STEPS` is the maximum
number of upward `nextafter` corrections across donor-bound and final certification, not the number of candidates
tested.

`final_certification` recomputes, at the tested binary64 value: donor
`CENTRAL_EXCEEDANCE_CLEARED`, receiver `NO_WORSE_HISTORICAL_FLOW_PROXY_STATE`, `phi ≤ phi_max_certified`, both
policy budgets, domain `phi ∈ [0,1]`, and per-horizon/total same-profile conservation within `1e-9`. The final
receiver no-worse check is mandatory even when a separately certified `phi_max` was already compared.

The public certificate emits `transfer_fraction`, `transfer_fraction_decimal` with 17 significant digits,
`phi_hex`, and `certify_up_steps`. The decimal and hexadecimal forms provide deterministic replay of the exact
published binary64 value. If the upward guard exhausts before certification, the result is
`PHI_CERTIFICATION_FAILED`; a weaker certificate MUST NOT be published.

The certification label is:

```text
transfer_fraction_certification = ALGEBRAIC_MINIMUM_CERTIFIED_UPWARD_FLOAT64
```

It means that the optimization minimum is defined algebraically, the published binary64 fraction is equal to or
slightly above that boundary when upward correction is required, and the published value is feasible at its exact
binary64 representation. It makes no representable-value minimality claim.

`DONOR_CENTRAL_RELIEF_INFEASIBLE` is otherwise unreachable in v1: `phi = 1` gives `c'_i(t) = 0 ≤ T_i(t)` for every
supported binding cell, so the donor goal is always achievable in exact arithmetic for a single receiver. The code
is reserved for a future stricter donor goal or multi-receiver/capacity-constrained extension. A bounded upward
Float64 certification failure in v1 emits `PHI_CERTIFICATION_FAILED` instead.

### 11.6 Why no MILP in v1, and when one would be justified

v1 is one continuous variable, a strictly increasing linear objective, and two closed intervals. The optimum is a
closed-form breakpoint. A solver would add an external dependency, non-determinism across versions and platforms,
tolerance semantics that are weaker than the exact algebra, and an opaque certificate — in exchange for nothing.

Even the natural next step is **not** a MILP: a single donor allocating to `K` receivers with per-receiver fractions
`phi_1 … phi_K` keeps every constraint linear, because `delta_j(t) = phi_j · c_i(t)` is linear in `phi_j` and each
receiver's no-worse breakpoints are linear inequalities. That extension is a **linear program**, and for a single
donor it still decomposes receiver by receiver.

A general MILP becomes appropriate only when genuinely discrete structure enters, for example:

- a cardinality limit on how many receiver relationships may be used, or a fixed activation cost / minimum
  transfer size per used pair (binary activation variables);
- multiple donors sharing receivers under joint per-receiver limits that are themselves discrete, such as staffed
  capacity in integer units from a future `physical_capacity_provider_v1`;
- a constraint or objective expressed as a **count** of severity states (e.g. "at most `n` `HIGH` cells"), which
  requires indicator variables — note that v1 forbids such counts as objectives anyway (section 5);
- discrete profile-compatibility or routing-permission logic (either/or admissibility);
- integer transfer units, which v1 explicitly forbids (section 4.3).

Until at least one of those exists as reviewed, data-backed structure, a solver is unjustified.

---

## 12. Fast exact evaluator and full verification

Two layers, with an explicit boundary on what each may claim.

### 12.1 Layer 1 — FAST EXACT EVALUATOR

Scope: **only** the donor and receiver daily cells of the canonical unit — the `2 × 14` registrations cells at
`(origin, profile)`. It is exact, not approximate: it applies the same algebra as the accepted engine to a restricted
cell set.

It computes the following **internal candidate evidence** for search, Pareto filtering, shortlisting, and the
full-engine agreement test:

| claimed field group | content |
|---|---|
| exact central transform | `c'_i(t)`, `c'_j(t)`, `moved(t)` for `t = 1 … 14` |
| exact scenario sensitivity transform | `L'(t)`, `U'(t)`, `scenario_uncertainty_status`, `scenario_uncertainty_method` for donor and receiver |
| exact pressure severity | per-cell `severity` and `source_reason_code` for donor and receiver |
| entity displayed severity | donor and receiver `max_severity_7d/14d`, displayed severity, and earliest `severity_evidence_horizon/date` attaining it |
| constraint satisfaction | `source_central_goal_satisfied`, `receiver_no_worse_constraint_satisfied`, `budget_constraint_satisfied`, `conservation_satisfied`, binding donor cell, binding receiver cell and predicate |
| transfer amounts | `transfer_fraction`, `transferred_expected_registrations_total`, `transferred_by_horizon` |
| Pareto dimensions | `receiver_worst_severity_after`, `receiver_min_central_headroom` |
| support / evidence | `donor_support_class`, `receiver_support_class`, `forecast_support_tier`, `receiver_range_evidence`, threshold support rungs, range availability, `receiver_range_masking_present` |
| range companion | `sensitivity_range_result`, `receiver_range_worst_severity_after` |

It **MUST NOT** claim, and MUST NOT emit even provisionally:

- final Inbox rank, Inbox membership, entered/left status;
- materiality status or operational priority status;
- final hierarchy diagnostics or hierarchy coherence results;
- entity aggregation beyond the displayed-severity fields listed above;
- deterministic operator explanation as a verified artifact;
- complete scenario output, scenario summary, or difference frames.

These records are not `DecisionAlternative` objects and MUST NOT appear in the published `alternatives` array.
`FAST_EVALUATOR_ONLY` is an internal candidate state only; no accepted or published alternative may retain it.

### 12.2 Layer 2 — FULL 6B.3 SCENARIO VERIFICATION

For every **shortlisted internal candidate**, v1 MUST run the unchanged accepted 6B.3 engine and compare.

Full verification establishes:

- exact bottom-up central hierarchy (region and national maximum absolute error `0` at tolerance `1e-9`);
- entity aggregation over the accepted grouping;
- fixed product materiality (`materiality_floor_expected_count = 1.0`, untuned);
- complete Inbox semantics — eligibility, support class, deterministic lexicographic rank, entered/left;
- deterministic operator explanation, with the accepted scenario wording rewrites;
- final daily and entity differences;
- conservation, scope invariance, input immutability, unchanged secondary target, unchanged raw quantiles,
  unchanged provenance and anomaly context, deterministic scientific hash.

Only after this does the candidate become a publishable `DecisionAlternative`, carry
`verification_state = VERIFIED_FULL_ENGINE`, and populate every contract-defined verification-only field with a
non-null value. A verification failure excludes the candidate and is recorded separately as a diagnostic; it never
creates a partially verified public alternative.

### 12.3 The agreement test — mandatory

> A future implementation test MUST prove the fast evaluator and the full 6B.3 engine agree on **every field the
> fast evaluator claims**, at tolerance `1e-9`.

Rules:

- the claimed-field set of section 12.1 is the normative test surface; adding a claimed field extends the test;
- numeric comparisons use absolute tolerance `1e-9` with `rtol = 0`, matching the accepted identity gate;
- categorical and string fields compare exactly;
- the test MUST run the full engine with the **certified** `transfer_fraction` value (section 11.5);
- a disagreement is a blocking defect. The fast evaluator MUST NOT be "reconciled" by widening tolerance, dropping
  a field from the claimed set, or post-adjusting its output.

### 12.4 The verification scenario specification

The full-verification run uses the accepted `inflow_transfer` lever with no engine change:

```text
scenario_type   = inflow_transfer
classification  = MECHANISTIC_ACCOUNTING_SCENARIO
scope           = { scope_type: region_profile,
                    region_id: <donor region>, profile_id: <profile>,
                    horizon_start: 1, horizon_end: 14 }
parameters      = { source_hospital_id: <donor>,
                    destination_hospital_id: <receiver>,
                    source_profile_id: <profile>,
                    destination_profile_id: <profile>,
                    fraction: <certified transfer_fraction> }
baseline_provenance = the accepted 6B.3 source chain, execution_mode = EVALUATION
```

`region_profile` scope is required because the accepted engine narrows a profile-constrained scope by hospital for
both endpoints; a `hospital_profile` scope cannot contain two hospitals. This is exactly why the v1 `SAME_REGION`
product policy and the accepted engine agree without modification. A future cross-region policy would use `profile`
scope, again with no engine change.

**Derived expectation to be verified, not claimed:** a same-region same-profile transfer conserves each
`(origin, target_date, region, profile)` sum exactly in exact arithmetic, so region and national central values must
equal their baseline values within tolerance `1e-9`. This is an additional acceptance invariant for full
verification (section 20, invariant 14b), not a fast-evaluator claim.

**Bit-equality MUST NOT be required for parent rows.** The accepted engine recomputes each parent central value as a
sum over its child terms, and after the transform those terms are `(1 − phi)·c_i(t)` and `c_j(t) + phi·c_i(t)`
instead of `c_i(t)` and `c_j(t)`. Binary64 summation of the reordered terms can therefore differ from the baseline
parent value by a few ULPs even though the exact-arithmetic sum is identical. The invariant is consequently stated at
tolerance `1e-9`, consistent with the accepted identity gate, and an implementation test MUST NOT assert bitwise
parent equality. This is distinct from the child-level bit-equality claims of section 4.3 and invariants 1, 7, and 8,
which hold exactly because those values are not re-summed.

### 12.5 Cost implication

The accepted 6B.3 engine recomputes baseline entity aggregation and Inbox preparation per scenario; the accepted
real-data suite took 1,803.5 s for four scenarios at peak 3,562.6 MiB. Full verification is therefore expensive per
alternative. This is the reason the two-layer design exists, and the reason the shortlist is bounded before
verification. Section 21 requires runtime and peak memory to be reported. Performance work MUST NOT change
scientific results.

---

## 13. Alternative set

The output of one canonical unit is exactly one

```text
DecisionAlternativeSet
```

containing **zero or more**

```text
DecisionAlternative
```

objects. Zero is a valid, complete, successful result (section 19).

The `alternatives` array contains **only** fully verified objects with
`verification_state = VERIFIED_FULL_ENGINE`. Fast-evaluator candidates, candidates omitted by the precommitted
shortlist bound, and candidates that fail full verification are separate non-alternative evidence records. They are
never typed, described, counted, or displayed as published `DecisionAlternative` objects.

v1 MUST NOT produce a single autonomous recommendation, a default selection, a highlighted choice, a "best" object,
or an implicit choice by ordering. **The system does not choose among the alternatives.**

### 13.1 Forbidden public fields

These field names MUST NOT exist anywhere in the contract, artifacts, code, or documentation:

```text
recommended_action
best_hospital
optimal_patient_route
```

Also forbidden as field names or values: `recommendation`, `recommended_*`, `best_*`, `optimal_*`, `chosen_*`,
`selected_action`, `action_plan`, `route`, `routing_decision`.

### 13.2 The word "optimal"

"Optimal" MUST NOT appear without an explicit mathematical qualifier that names the objective and the constraint
set. The approved phrase is:

```text
minimum_transfer_under_stated_constraints
```

Approved prose forms: "minimum certified transfer fraction under the stated constraints", "exact minimum of the
stated objective over the stated feasible set". Forbidden: "optimal transfer", "optimal hospital", "optimal
routing", "the optimal solution", "optimally".

---

## 14. Materiality and support

### 14.1 Donor search — materiality applies

Donor search considers the **materially eligible primary Inbox only**. Excluded:

- `ZERO_BASELINE_LOW_VOLUME_ATTENTION` (`operational_priority_status = zero_baseline_low_volume`);
- `UNSUPPORTED_DATA_QUALITY` (`operational_priority_status = unsupported_data_quality`).

The fixed materiality rule is accepted product triage — a `1.0` expected count/day floor on supported
zero-threshold rows, evaluated on the entity's severity evidence cell — and is **not** tuned, recalibrated, or
extended by 6B.4. It does not rewrite source severity.

### 14.2 Receiver safety — materiality does not apply

Receiver harm is evaluated on **raw** severity, cell by cell, with no materiality filtering (section 8.3).

### 14.3 Evidence tiers

Forecast support is normalized onto this axis:

```text
DIRECT_SUPPORTED
FALLBACK_LIMITED
UNSUPPORTED       → rejected, never an alternative
```

Per party, after the explicit normalization in section 14.4:

- `donor_support_class` — the donor's normalized accepted `priority_support_class`;
- `receiver_support_class` — the receiver's normalized accepted `priority_support_class`.

Alternative-level forecast-support tier:

```text
forecast_support_tier = DIRECT_SUPPORTED   if donor and receiver are both DIRECT_SUPPORTED
                        FALLBACK_LIMITED   otherwise
```

`forecast_support_tier` is a floor, never an average and never a blend. Receiver range evidence is a separate axis:

```text
receiver_range_evidence = COMPLETE       if every affected receiver cell has usable accepted range evidence
                          RANGE_LIMITED  otherwise
```

`receiver_range_masking_present = true` implies `receiver_range_evidence = RANGE_LIMITED` and
`sensitivity_range_result = RANGE_EVIDENCE_INCOMPLETE`. A range-limited alternative may be fully verified and
published with disclosure, including when its `forecast_support_tier` is `DIRECT_SUPPORTED`, but it MUST NOT count
toward the primary acceptance cohort. The primary cohort requires both `forecast_support_tier = DIRECT_SUPPORTED`
and `receiver_range_evidence = COMPLETE`.

Acceptance metrics MUST be reported on both axes and, where composition matters, per
`(donor support class, receiver support class)` pair. **Never combine their acceptance metrics silently.** A single
pooled "alternative rate" across either axis is a reporting defect.

Forecast support, threshold support, and range availability remain three independent dimensions and MUST NOT be
merged into one support score.

### 14.4 Normalized contract vocabulary

6B.4 uses normalized public vocabulary rather than claiming enum identity with its accepted inputs:

| source concept | accepted source literal / condition | normalized 6B.4 contract value |
|---|---|---|
| target | `registrations` | `REGISTRATIONS` |
| priority support | `direct_supported` | `DIRECT_SUPPORTED` |
| priority support | `fallback_or_limited_history` | `FALLBACK_LIMITED` |
| receiver range completeness | usable accepted scenario sensitivity evidence on every affected cell | `COMPLETE` |
| receiver range completeness | any missing or masked scenario sensitivity evidence | `RANGE_LIMITED` |

In particular, `FALLBACK_LIMITED` is normalized 6B.4 vocabulary; it is **not** the literal accepted source value
`fallback_or_limited_history`. Source literals remain unchanged in accepted inputs and provenance.

---

## 15. Output contract

Normative schemas. Both objects are **candidate-independent**: no model family, artifact column layout, training
parameter, fold, or candidate name appears in them, consistent with ADR 0005.

### 15.1 `DecisionAlternativeSet`

| field | type | semantics |
|---|---|---|
| `optimizer_contract_version` | required string | `constrained-decision-alternatives-v1`; a schema key, not a capability claim |
| `origin` | required date | accepted forecast origin |
| `target` | required constant | `REGISTRATIONS` |
| `profile` | required string | profile id shared by donor and receivers |
| `donor_signal_ref` | required object | accepted donor signal identity: `signal_id`, hospital, profile, target, origin, displayed severity, `priority_support_class`, `operational_priority_status`, `materiality_status`, plus `B_i` as `binding_horizons` |
| `search_policy` | required object | donor cohort rule, receiver candidate rule, `donor_goal`, `decision_basis`, `algorithm`, Pareto dimensions, display order, `identity_sha256` |
| `constraint_policy` | required object | scientific constraint set version, product policy, user budget values, `PHI_GUARD_MAX_STEPS`, `identity_sha256` |
| `evidence_policy` | required object | definitions and counts for the orthogonal `forecast_support_tier` and `receiver_range_evidence` axes, plus donor/receiver support-class pair counts; no pooled tier value |
| `alternatives` | required list | zero or more fully verified `DecisionAlternative` objects, in deterministic display order; every member has `verification_state = VERIFIED_FULL_ENGINE` |
| `alternatives_dropped_by_shortlist_bound` | required list | non-alternative evidence records identifying otherwise feasible candidates not sent to full verification; never `DecisionAlternative` objects |
| `verification_failures` | required list | non-alternative diagnostics for candidates excluded after `FULL_VERIFICATION_FAILED`; never `DecisionAlternative` objects |
| `abstention_status` | required object | `{abstained, codes[], rejected_receivers[]}` with a code per rejected receiver |
| `provenance` | required object | accepted source run ids, 6B.3 scenario contract version and scientific identity, config identity, code identity, `execution_mode` |
| `human_review_required` | required constant | `true` |
| `execution_mode` | required constant | `EVALUATION` |
| `serving_claim` | required constant | `false` |

Additional normative set-level fields:

| field | type | semantics |
|---|---|---|
| `canonical_unit_id` | required string | deterministic hash of the canonical unit identity |
| `receiver_candidates_considered` | required integer | before eligibility filtering |
| `receiver_candidates_eligible` | required integer | after eligibility filtering |
| `donor_minimum_transfer_fraction` | required float | `phi_min`, receiver-independent (Lemma L5) |
| `donor_zero_threshold_binding_present` | required boolean | section 11.3 |
| `limitations` | required list | includes `NOT_PHYSICAL_CAPACITY_VALIDATED` and `THRESHOLD_COMPARATOR_ASSUMPTION` |
| `scientific_output_sha256` | required string | deterministic hash over the scientific fields of the set, excluding timestamps |

### 15.2 `DecisionAlternative`

Required fields, as specified:

| field | type | semantics |
|---|---|---|
| `alternative_id` | required string | deterministic hash over canonical unit, receiver, goal, policies, and the certified fraction; no timestamp input |
| `donor` | required object | hospital, region, profile, series id |
| `receiver` | required object | hospital, region, profile, series id |
| `transfer_fraction` | required float | the exact published binary64 `phi`, upward-certified from `phi_min_alg` |
| `transferred_expected_registrations_total` | required float | `phi · Σ_t c_i(t)` |
| `transferred_by_horizon` | required list | per `t = 1 … 14`: `{horizon, target_date, moved}` |
| `baseline_donor_state` | required object | per-horizon baseline cells (section 15.3) |
| `scenario_donor_state` | required object | per-horizon scenario cells |
| `baseline_receiver_state` | required object | per-horizon baseline cells |
| `scenario_receiver_state` | required object | per-horizon scenario cells |
| `source_central_goal_satisfied` | required boolean | `CENTRAL_EXCEEDANCE_CLEARED` achieved on all of `B_i` |
| `receiver_no_worse_constraint_satisfied` | required boolean | `NO_WORSE_HISTORICAL_FLOW_PROXY_STATE` on all horizons |
| `budget_constraint_satisfied` | required boolean | both policy budgets respected |
| `conservation_satisfied` | required boolean | per-horizon and total conservation within `1e-9` |
| `donor_support_class` | required enum | `DIRECT_SUPPORTED` \| `FALLBACK_LIMITED` |
| `receiver_support_class` | required enum | `DIRECT_SUPPORTED` \| `FALLBACK_LIMITED` |
| `receiver_min_central_headroom` | required float | `min_{t ∈ A} ( T_j(t) − c'_j(t) )`; signed; modelled headroom under the historical-flow proxy, never capacity |
| `receiver_worst_severity_after` | required enum | worst scenario `PressureSeverity` over `t ∈ A` |
| `decision_basis` | required constant | `CENTRAL_CASE` |
| `forecast_support_tier` | required enum | `DIRECT_SUPPORTED` \| `FALLBACK_LIMITED`; normalized floor of donor and receiver forecast support |
| `receiver_range_evidence` | required enum | `COMPLETE` \| `RANGE_LIMITED`; independent of forecast support |
| `sensitivity_range_result` | required enum | `ROBUST_TO_TRANSFORMED_RANGE` \| `NOT_ROBUST_TO_TRANSFORMED_RANGE` \| `RANGE_EVIDENCE_INCOMPLETE` |
| `range_recalibrated` | required constant | `false` |
| `coverage_guarantee` | required constant | `false` |
| `feasibility_status` | required constant | `NOT_PHYSICAL_CAPACITY_VALIDATED` |
| `capacity_checked` | required constant | `false` |
| `causal_effect_claimed` | required constant | `false` |
| `verification_state` | required constant | `VERIFIED_FULL_ENGINE`; internal candidate states are not legal in this public object |
| `human_review_required` | required constant | `true` |
| `explanation` | required object | deterministic explanation (section 18) |
| `provenance` | required object | accepted lineage plus the exact verification scenario specification |
| `execution_mode` | required constant | `EVALUATION` |
| `serving_claim` | required constant | `false` |

Additional normative fields:

| field | type | semantics |
|---|---|---|
| `transfer_fraction_certification` | required constant | `ALGEBRAIC_MINIMUM_CERTIFIED_UPWARD_FLOAT64` |
| `transfer_fraction_decimal` | required string | decimal representation of the exact binary64 `transfer_fraction`, using 17 significant digits |
| `phi_hex` | required string | hexadecimal representation of the exact binary64 `transfer_fraction` |
| `certify_up_steps` | required integer | upward `nextafter` steps used by certification (section 11.5) |
| `donor_binding_cell` | required object | `argmax` cell of `phi_min`: horizon, target date, `c_i`, `T_i` |
| `donor_binding_horizons` | required list | `B_i` |
| `donor_zero_threshold_binding_present` | required boolean | section 11.3 |
| `donor_residual_range_driven_high_horizons` | required list | horizons where `L'_i(t) > T_i(t)` after transfer |
| `donor_severity_after` | required enum | donor entity displayed severity after transfer |
| `receiver_binding_cell` | nullable object | cell and predicate producing `phi_max`, null when no breakpoint applies |
| `receiver_phi_max` | required float | certified `phi_max` |
| `receiver_range_masking_present` | required boolean | section 10.4 |
| `receiver_range_worst_severity_after` | required enum | worst range-driven state over `A` |
| `pair_conservation_max_absolute_error` | required float | measured, must be `≤ 1e-9` |
| `limitations` | required list | includes `NOT_PHYSICAL_CAPACITY_VALIDATED`, `THRESHOLD_COMPARATOR_ASSUMPTION`, and `PHYSICAL_FEASIBILITY_UNKNOWN` |
| `verification_only_fields` | required non-null object | Inbox membership/rank, entered/left, materiality status, hierarchy coherence, and difference summaries established by full verification |

### 15.3 Per-horizon state object

Each of the four state objects contains, for `t = 1 … 14`:

`horizon`, `target_date`, `central`, `sensitivity_lower`, `sensitivity_upper`, `uncertainty_status` (baseline) or
`scenario_uncertainty_status` (scenario), `scenario_uncertainty_method` where applicable, `threshold_value`,
`threshold_status`, `threshold_fallback_level`, `severity`, `source_reason_code`, plus entity-level
`displayed_severity`, `max_severity_7d`, `max_severity_14d`, `severity_evidence_horizon`,
`severity_evidence_date`.

Baseline state objects carry accepted calibrated field names; scenario state objects carry scenario-scoped names
only. A scenario value MUST NOT be published under an accepted calibrated name, and MUST NOT be described as
calibrated, a confidence interval, a prediction interval, an 80% interval, or a raw quantile — exactly as the
accepted 6B.3 vocabulary rule requires.

### 15.4 Determinism

All identities and hashes are computed over scientific content only. Timestamps, runtime metadata, host, resource
profile, and wall-clock values MUST be excluded from every identity, mirroring the accepted 6B.3 rule that an
identical scientific specification with a different `created_at` yields an identical scientific identity. Two runs
of the same specification on the same accepted inputs MUST produce byte-identical scientific output and identical
hashes (invariant 16, section 20).

---

## 16. Pareto filtering and display ordering

### 16.1 No scalarization

There is **no weighted scalarization**, no composite index, and no tie-breaking score. Alternatives are compared on
transparent dimensions only.

### 16.2 The three transparent dimensions

| # | dimension | direction | meaning |
|---|---|---|---|
| 1 | `total_synthetic_flow_moved` | minimize | `phi · Σ_t c_i(t)`, total synthetic expected registrations moved |
| 2 | `receiver_worst_severity_after` | minimize | worst scenario `PressureSeverity` over affected receiver horizons, by accepted `SEVERITY_RANK` |
| 3 | `receiver_min_central_headroom` | maximize | `min_{t ∈ A} ( T_j(t) − c'_j(t) )` under the historical-flow proxy |

### 16.3 Dominance

`a` dominates `b` if `a` is no worse on every dimension and strictly better on at least one, comparing dimension 1
and 2 as minimize and dimension 3 as maximize.

Rules:

- dominance is evaluated **within one canonical unit** only;
- dominance is evaluated **within one evidence stratum** only, where a stratum is the pair
  `(forecast_support_tier, receiver_range_evidence)`. Alternatives on different forecast-support or range-evidence
  axes never eliminate one another, because folding either evidence axis into dominance would be a hidden preference;
- Pareto filtering is used **only** to remove dominated alternatives. It never ranks, scores, or selects;
- by Lemma L5, dimension 1 is constant within a canonical unit, so within one unit the filter discriminates on
  dimensions 2 and 3 only. Dimension 1 remains normative because it is the published objective and because it
  discriminates across budget rungs and across future multi-donor or multi-goal extensions. The set is therefore a
  set of **equally minimal-transfer options that differ in receiver-side modelled impact**, and this MUST be stated
  wherever a set is displayed;
- if every candidate is dominated — which can only happen through a defect, since dominance is a strict partial
  order — the unit abstains with `NO_NON_DOMINATED_ALTERNATIVE`.

### 16.4 Deterministic display ordering

After Pareto filtering, the surviving internal candidates are ordered by:

1. `forecast_support_tier`: `DIRECT_SUPPORTED` before `FALLBACK_LIMITED`;
2. `receiver_range_evidence`: `COMPLETE` before `RANGE_LIMITED`;
3. smaller `transferred_expected_registrations_total`;
4. lower `receiver_worst_severity_after` (accepted `SEVERITY_RANK`);
5. larger `receiver_min_central_headroom`;
6. stable receiver id ascending (`region_id`, `hospital_id`, `series_id` for total stability).

**This ordering is NOT a claim of real-world superiority.** It is a deterministic, reproducible presentation order
so that two runs and two reviewers see the same list. It is not a ranking of quality, safety, preference,
appropriateness, or benefit. Position 1 is not a recommendation.

### 16.5 Shortlist bound

Full verification is expensive (section 12.5), so a bounded shortlist is taken **after** Pareto filtering and
**after** display ordering, using `shortlist_max_alternatives`, fixed in configuration before the run.

- the bound MUST be precommitted, never chosen after seeing outcomes;
- the bound is applied per canonical unit and per evidence stratum, so the primary direct/complete stratum is never
  crowded out by fallback or range-limited strata;
- **no silent caps**: the set MUST publish `shortlist_bound`, `alternatives_pareto_surviving`,
  `alternatives_shortlisted`, and `alternatives_dropped_by_shortlist_bound`. Dropped records are a separate
  non-alternative evidence structure, MUST NOT use the `DecisionAlternative` schema, and MUST NOT appear in
  `alternatives`. A truncated set MUST NOT read as a complete set.

---

## 17. Configuration surface (normative for the future implementation)

The implementation configuration is `ml/configs/decision_alternatives.yaml`; the following keys are normative:

```text
schema_version
optimizer_contract_version            # constrained-decision-alternatives-v1
target                                # registrations (only legal value)

source_hierarchy_run                  # flow-hierarchy-6b2b3-real-v1
source_pressure_run                   # flow-pressure-6b2c1-real-v2
source_prioritization_run             # signal-prioritization-6b2c2-real-v2
source_scenario_run                   # flow-scenario-6b3-real-v1
scenario_contract_version             # forecast-stress-test-v1

donor_goal                            # CENTRAL_EXCEEDANCE_CLEARED (only legal value)
decision_basis                        # CENTRAL_CASE (only legal value)
algorithm                             # EXACT_BREAKPOINT_ENUMERATION_V1 (only legal value)

donor_cohort:
  origins                             # accepted origins, precommitted
  top_n_primary_donors                # precommitted direct-supported cohort size
  top_n_fallback_donors               # separately precommitted fallback/limited secondary-evidence cohort size
  severities                          # [ELEVATED, HIGH]
  require_central_driven               # true
  primary_tier                        # direct_supported
  include_fallback_tier_separately    # true

receiver_policy:
  geographic_scope                    # SAME_REGION
  require_supported_threshold_all_affected_horizons   # true
  require_aligned_full_horizon_window                 # true
  eligible_receiver_ids               # null or explicit allow-list

transfer_budget_ladder                # [0.05, 0.10, 0.25, 1.00]
max_total_synthetic_transfer          # null or explicit
shortlist_max_alternatives            # precommitted
phi_guard_max_steps                   # 8
float_tolerance                       # 1e-9

materiality_config_reference          # signal_prioritization.yaml#materiality_floor_expected_count
range_recalibrated                    # false (validated constant)
coverage_guarantee                    # false (validated constant)
capacity_checked                      # false (validated constant)
causal_effect_claimed                 # false (validated constant)
human_review_required                 # true (validated constant)
autonomous_action                     # false (validated constant)
execution_mode                        # EVALUATION (only legal value)
serving_claim                         # false (validated constant)
```

The loader MUST reject any configuration that changes a validated constant, names a target other than
`registrations`, names an unaccepted source run, or supplies a budget value derived from data. Every `identity_sha256`
in `search_policy` / `constraint_policy` is computed over the resolved configuration content.

---

## 18. Deterministic explanation

The explanation is deterministic, template-driven, and computed without any LLM. **No LLM may be in the path** of
producing, ranking, summarizing, or rewriting it.

### 18.1 Required content

Every alternative's explanation MUST state all eight items:

1. **synthetic flow amount** — the certified transfer fraction and the total synthetic expected registrations moved,
   named as synthetic;
2. **donor central goal** — that the donor's central threshold exceedance is removed on its binding horizons, and
   which horizon binds;
3. **receiver constraint** — that no affected receiver day's modelled historical-flow proxy state is higher than its
   baseline state, and which receiver cell is binding when one is;
4. **flow conservation** — that the same-profile, same-date total is conserved within `1e-9`;
5. **evidence axes** — the donor and receiver support classes separately, the normalized
   `forecast_support_tier`, and the independent `receiver_range_evidence` value;
6. **sensitivity-range companion result** — the `sensitivity_range_result` value, with the explicit statement that
   the range is not recalibrated and carries no probability, confidence level, or coverage guarantee;
7. **operational / capacity limitation** — that physical feasibility is unknown, capacity was not checked, and the
   receiver threshold comparator is an assumption;
8. **human review requirement** — that the alternative is a mathematical alternative requiring human review and is
   not an action, instruction, or recommendation.

Where section 6.4 non-claims apply (residual range-driven `HIGH`, non-`NORMAL` donor state, Inbox membership not
established), the explanation MUST state them.

### 18.2 Language rules

The explanation MUST NOT contain causal language. The accepted prohibited tokens are enforced unchanged
(`caused`, `causes`, `causal`, `driver`, `drives`, `attributable`), extended for 6B.4 with:

`recommend`, `recommended`, `should transfer`, `route`, `routing`, `reroute`, `optimal`, `best`, `capacity`,
`spare capacity`, `beds`, `bed`, `staffing`, `occupancy`, `available`, `availability`, `accept patients`,
`absorb`, `prevent`, `prevents`, `prevented`, `avoid overload`, `reduce waiting`, `waiting time`, `refusal`,
`outcome improves`, `benefit`, `safe`, `feasible`.

A term from the list MAY appear only inside an explicit negation that is itself part of the required limitation
text (for example "physical capacity was not checked"). The implementation MUST enforce this with a normative
allow-list of negated phrases, not with a substring exemption.

### 18.3 Approved phrasing skeleton

```text
Moving a synthetic fraction <phi> of this hospital/profile's expected registrations to
<receiver> for the same profile and the same target dates removes the donor's central
historical-flow threshold exceedance on horizons <B_i>, with horizon <binding> binding.
Under the accepted historical-flow proxy, no affected day of the receiver's modelled state
is higher than its baseline modelled state. The same-profile, same-date total is conserved
within 1e-9. Donor evidence: <donor tier>. Receiver evidence: <receiver tier>.
Derived scenario sensitivity range result: <sensitivity_range_result>; this range is not
re-calibrated and carries no probability, confidence level, or coverage guarantee.
Physical feasibility is unknown and physical capacity was not checked; the receiver's
historical-flow threshold was estimated without this synthetic flow. This is a mathematical
alternative under stated constraints and requires human review.
```

---

## 19. Abstention

Abstention is a **valid, complete result**. The engine MUST NOT relax a constraint, widen a budget, drop a horizon,
substitute a receiver, soften a threshold, or weaken the donor goal in order to return something.

### 19.1 Required codes

| code | meaning |
|---|---|
| `NO_ELIGIBLE_RECEIVER` | no hospital satisfies receiver eligibility (section 7) |
| `DONOR_CENTRAL_RELIEF_INFEASIBLE` | no `phi ∈ [0,1]` achieves `CENTRAL_EXCEEDANCE_CLEARED` under certification |
| `TRANSFER_BUDGET_INSUFFICIENT` | `phi_min` exceeds `max_transfer_fraction`, or the moved total exceeds `max_total_synthetic_transfer` |
| `RECEIVER_BLOCKED` | every eligible receiver has `phi_max < phi_min` |
| `INSUFFICIENT_SUPPORT` | required support evidence is missing on donor or every receiver |
| `UNSUPPORTED_SIGNAL` | the donor signal is threshold-unsupported or otherwise outside the supported evidence tier |
| `NO_NON_DOMINATED_ALTERNATIVE` | Pareto filtering leaves nothing |

### 19.2 Additional codes (v1 extensions)

| code | meaning |
|---|---|
| `DONOR_NOT_CENTRAL_DRIVEN` | `B_i = ∅`; includes every `WATCH`-only and range-driven-only signal |
| `DONOR_NOT_MATERIALLY_ELIGIBLE` | donor is in `zero_baseline_low_volume_attention` or `unsupported_data_quality` |
| `DONOR_TIER_EXCLUDED` | donor is `FALLBACK_LIMITED` and the fallback tier is not enabled for this run |
| `RECEIVER_UNSUPPORTED_EVIDENCE` | an affected receiver cell has `threshold_status = unsupported` |
| `RECEIVER_ALIGNMENT_INCOMPLETE` | the receiver lacks an aligned complete horizon 1–14 cell set |
| `RECEIVER_OUTSIDE_SAME_REGION_POLICY` | a same-profile peer is excluded by the v1 `SAME_REGION` product policy |
| `RECEIVER_NOT_ALLOW_LISTED` | a same-profile peer is excluded by the configured receiver allow-list |
| `PHI_CERTIFICATION_FAILED` | the bounded certification guard could not certify any fraction |
| `FULL_VERIFICATION_FAILED` | the full 6B.3 engine disagreed with a claimed field at tolerance `1e-9` |

`FULL_VERIFICATION_FAILED` excludes that candidate from `alternatives` and records it in the set's
`verification_failures` diagnostic and applicable abstention diagnostics. It does not create a public object with
`verification_state = VERIFICATION_FAILED`; a partially verified alternative is never published. The disagreement
remains a blocking defect for the run.

### 19.3 Standing qualifier

Every returned alternative, without exception, carries:

```text
PHYSICAL_FEASIBILITY_UNKNOWN
```

equivalently `feasibility_status = NOT_PHYSICAL_CAPACITY_VALIDATED` with `capacity_checked = false`.

An empty `alternatives` list with a populated `abstention_status` is a successful, publishable result. **No-solution
is a valid result.**

---

## 20. Acceptance invariants

Every invariant is a test. A failure is blocking.

| # | invariant |
|---|---|
| 1 | `phi = 0` reproduces the baseline exactly — every donor and receiver field bit-identical, and the full-engine identity gate passes at `1e-9` |
| 2 | registrations only; no other target is read as a decision target or modified |
| 3 | same profile for donor and receiver in every alternative |
| 4 | same origin, same target date, same horizon for every unit of moved flow |
| 5 | flow conservation per horizon and in total within `1e-9` |
| 6 | donor flow nonnegative for every horizon and every `phi ∈ [0,1]`; donor severity rank never increases |
| 7 | `cohort_hospitalizations` bit-unchanged |
| 8 | thresholds, threshold status, fallback rung, and threshold provenance bit-unchanged |
| 9 | unsupported donor rejected — never evaluated, never returned, never described as marginal |
| 10 | unsupported receiver rejected — an unsupported affected cell rejects the receiver |
| 11 | receiver severity never worsens on any horizon, evaluated on raw severity without the materiality floor |
| 12 | both policy budgets respected; a budget is never inferred from data |
| 13 | support, fallback, and range provenance preserved; a transformed fallback forecast never becomes directly supported |
| 14 | hierarchy exact after full verification — region and national maximum absolute error `0` at tolerance `1e-9` |
| 14b | region and national central values equal their baseline values within tolerance `1e-9` for a same-region same-profile transfer — exact in exact arithmetic, **not** bitwise, because parent values are re-summed (section 12.4) |
| 15 | fast evaluator equals the full engine on every claimed field at tolerance `1e-9` |
| 16 | deterministic outputs and hashes; timestamps excluded from every identity; two runs byte-identical |
| 17 | no hidden scalar score anywhere — no weighted objective, no composite index, no learned ranker |
| 18 | Pareto dominance correct: reflexive-free strict partial order, evaluated within canonical unit and the same `(forecast_support_tier, receiver_range_evidence)` stratum only |
| 19 | abstention supported and exercised; zero alternatives is a valid published result; no constraint is silently relaxed |
| 20 | `human_review_required = true` on every set and every alternative |
| 21 | `capacity_checked = false` on every alternative |
| 22 | `causal_effect_claimed = false` on every alternative |
| 23 | `WATCH`-only donor optimization forbidden — such signals abstain with `DONOR_NOT_CENTRAL_DRIVEN` |
| 24 | the scenario sensitivity range is never treated as a calibrated probability: `range_recalibrated = false`, `coverage_guarantee = false`, and `RANGE_EVIDENCE_INCOMPLETE` never reads as robust |
| 25 | no operational recommendation wording — the forbidden field names and the forbidden lexicon are enforced by test over contract keys, values, artifacts, and explanation text |

Additional derived invariants, proved in section 11 and asserted in code:

| # | invariant |
|---|---|
| 26 | receiver cell severity rank is monotone non-decreasing in `phi`; the no-worse feasible set is a single closed interval `[0, phi_max]` |
| 27 | donor cell severity rank is monotone non-increasing in `phi`; the donor goal set is a single closed interval `[phi_min, 1]` |
| 28 | `phi_min` is receiver-independent (Lemma L5), so `transferred_expected_registrations_total` is identical across all alternatives of one canonical unit |
| 29 | the published `transfer_fraction` satisfies every certified constraint at its exact binary64 value and is obtained from the algebraic minimum using at most `PHI_GUARD_MAX_STEPS` upward `nextafter` corrections; no downward tightening below the algebraic minimum is permitted |
| 30 | `receiver_range_masking_present` is published whenever any affected receiver cell lacks a usable range; it implies `receiver_range_evidence = RANGE_LIMITED` and `RANGE_EVIDENCE_INCOMPLETE`, and excludes the alternative from the primary direct/complete cohort |
| 31 | no solver, MILP, CP, LP, metaheuristic, or learned-policy dependency is introduced |
| 32 | no accepted 6B.3 / 6B.2C / 6B.2C-2 code path is modified; the verification run uses the accepted `inflow_transfer` lever unchanged |
| 33 | no patient-level, referral-level, or individual-level object exists in the contract |
| 34 | shortlist truncation is published (`alternatives_dropped_by_shortlist_bound`); no silent cap |
| 35 | every published `DecisionAlternative` has `verification_state = VERIFIED_FULL_ENGINE`; no `FAST_EVALUATOR_ONLY` or failed candidate appears in `DecisionAlternativeSet.alternatives` |

---

## 21. Real-data acceptance protocol

Every parameter below MUST be fixed in configuration and reviewed **before** any optimizer outcome is inspected.
Precommitment is part of the acceptance, not a formality: selecting `N`, the origins, the budget ladder, or the
shortlist bound after seeing results invalidates the run.

### 21.1 Primary donor cohort

```text
top N materially eligible
    direct-supported
    REGISTRATIONS
    signals
  by the accepted Inbox ordering
  at the accepted origins
```

- ordering is the accepted deterministic lexicographic `inbox_rank`; no reordering, no re-scoring;
- `N` MUST be fixed in configuration before the real run;
- accepted origins are the accepted validation origins and the accepted final origin of the closed chain; the run
  MUST NOT invent a new origin;
- the `FALLBACK_LIMITED` donor tier, if evaluated, is a separate cohort with its own `N` and its own reported
  metrics.

### 21.2 Receiver policy

```text
same profile
same region
supported threshold on every affected horizon
aligned complete horizon 1–14 cell set
receiver != donor
```

### 21.3 Predefined transfer budget ladder

```text
0.05
0.10
0.25
1.00
```

These are **policy stress budgets, NOT capacity**. They are reviewed policy values, not measured limits, not
inferred from data, and not operational allowances. Each rung is a separate reported configuration; results MUST NOT
be pooled across rungs.

### 21.4 Decision basis

- primary basis: `CENTRAL_CASE`;
- companion, reported for every candidate: `SENSITIVITY_RANGE_CASE`.

### 21.5 Required report

Reported per budget rung and on both orthogonal evidence axes — `forecast_support_tier` and
`receiver_range_evidence` — never pooled. The primary acceptance cohort is exactly
`(DIRECT_SUPPORTED, COMPLETE)`; `RANGE_LIMITED` results are secondary disclosed evidence and do not count as primary
acceptance:

1. signals evaluated;
2. at-least-one-alternative rate;
3. `NO_ELIGIBLE_RECEIVER` rate;
4. `DONOR_CENTRAL_RELIEF_INFEASIBLE` rate;
5. `TRANSFER_BUDGET_INSUFFICIENT` rate;
6. `RECEIVER_BLOCKED` rate;
7. minimum transfer fraction distribution (min, quartiles, median, max), plus the share with `phi_min = 1.0` and the
   share with `donor_zero_threshold_binding_present = true`;
8. transferred expected registrations distribution;
9. direct / fallback composition, reported per `(donor tier, receiver tier)` pair, crossed with
   `receiver_range_evidence`;
10. receiver worsening count;
11. full-engine verification rate for shortlisted internal candidates;
12. runtime;
13. peak memory.

Also required, as v1-specific diagnostics: `RECEIVER_UNSUPPORTED_EVIDENCE` and `RECEIVER_ALIGNMENT_INCOMPLETE`
rates, `receiver_range_masking_present` share, `sensitivity_range_result` composition,
`donor_residual_range_driven_high_horizons` non-empty share, `certify_up_steps` distribution, zero-threshold receiver
counts split by baseline `NORMAL` / `ELEVATED` / `HIGH` and resulting
`RECEIVER_BLOCKED` counts, `verification_failures`, and `alternatives_dropped_by_shortlist_bound`.

### 21.6 Required outcomes

```text
receiver worsening count                      = 0
full-engine verification rate (shortlisted)   = 100%
```

Any receiver worsening, or any shortlisted internal candidate that the full engine does not reproduce at `1e-9`, is a
blocking defect. It MUST NOT be resolved by widening tolerance, excluding the alternative, or relabelling the
constraint.

### 21.7 Forbidden report content

The acceptance report MUST NOT contain, in any form:

- patient benefit;
- wait or waiting-time reduction;
- refusal reduction;
- clinical outcome benefit;
- overload prevention or avoided incidents;
- capacity utilisation, freed beds, or occupancy change;
- an inferred operational recommendation, or a count of "recommended transfers".

### 21.8 Not run by this specification

No scenario run, optimizer run, or real-data evaluation is executed by this specification task. There is no 6B.4
accepted run, no artifact, and no measured result yet.

---

## 22. Customer dependencies — explicitly unresolved

These MUST remain open. They MUST NOT be solved by assumption, by default value, by inference from data, or by a
placeholder that later reads as agreed.

- allowed operational actions — whether any transfer-like action is permitted at all;
- receiver eligibility rules as the customer defines them;
- hospital service / profile compatibility;
- geography rules, catchment areas, and referral territories;
- contractual and referral restrictions;
- physical capacity;
- staffed beds;
- occupancy and census;
- maximum transfer policies and who sets them;
- operator roles;
- approval workflow and accountability for a reviewed alternative.

Until these exist, `geographic_scope = SAME_REGION` and every budget value are **placeholders labelled as policy**,
not agreed rules. The v1 alternative set is an analytical artifact for review, not an operational proposal.

---

## 23. Future capacity extension

Real capacity data, when it exists and is independently reviewed, can be added as a **new constraint / provider
layer** without redesigning this contract. The canonical unit, decision variable, objective, orthogonal evidence axes,
abstention semantics, and output schema stay as specified; a capacity provider adds constraints and fields.

Possible future fields and constraints — **FUTURE ONLY, not implemented, not reserved as satisfied**:

```text
capacity_checked = true
physical_capacity_provider version        # e.g. physical_capacity_provider_v1
staffed operational capacity
occupancy / free capacity
profile compatibility
```

Rules for any such future work:

- a future `physical_capacity_provider_v1` requires real capacity data, agreed interpretation, and independent
  review. It **cannot** be introduced by renaming `historical_flow_proxy_v1`, exactly as ADR 0005 already requires;
- `capacity_checked = true` is legal only when a reviewed capacity provider actually evaluated the alternative;
- `feasibility_status` may leave `NOT_PHYSICAL_CAPACITY_VALIDATED` only through that reviewed provider;
- a future multi-receiver allocation with a single donor is a **linear program**, not a MILP (section 11.6);
- a general MILP is justified only by genuinely discrete structure: receiver cardinality limits, per-pair activation
  costs or minimum transfer sizes, integer capacity units, count-based constraints requiring indicator variables, or
  either/or admissibility logic;
- v1 MUST NOT implement, stub, scaffold, or pre-wire any of this.

---

## 24. Forbidden interpretations

These interpretations are explicitly forbidden. Each is forbidden in code, configuration, field names, field values,
artifacts, documentation, commit messages, operator-facing text, demos, and verbal presentation.

1. "AI recommends routing patients" — nothing is recommended and no patient is routed;
2. "the receiver has spare capacity" — no capacity data exists;
3. "the receiver can accept patients" — acceptance is not modelled;
4. "waiting time will decrease" — waiting time is not modelled;
5. "refusals will decrease" — refusal flow is not modelled, and no refusal forecast is accepted;
6. "patient outcome improves" — no outcome is modelled;
7. "overload is prevented" — no overload state exists; the comparator is a historical-flow quantile;
8. "physical feasibility is established" — feasibility is unknown by construction;
9. "causal intervention benefit" — the transform is deterministic accounting on a forecast, not an identified
   intervention;
10. "optimal operational policy" — the only optimum is of the stated mathematical objective over the stated
    constraint set;
11. "live serving proposal" — all current evidence is retrospective `EVALUATION`.

**All current evidence is retrospective `EVALUATION`.** There is no legal-origin serving execution, no live scoring,
and no serving claim, consistent with the accepted 6B.2D boundary.

### 24.1 Vocabulary substitution table

| forbidden | required |
|---|---|
| available / has capacity / can accept / can absorb | same-profile peer series with modelled headroom under the historical-flow proxy |
| capacity headroom / free capacity | modelled central headroom under the historical-flow proxy (`T_j(t) − c'_j(t)`) |
| recommended transfer / best hospital | minimum transfer under stated constraints; alternative |
| optimal (bare) | minimum of the stated objective over the stated feasible set |
| patients moved / patients transferred | synthetic expected registrations moved |
| transfer plan / routing decision | decision alternative requiring human review |
| overload avoided / pressure prevented | central historical-flow threshold exceedance removed under the surrogate |
| safe receiver / feasible transfer | receiver with no modelled worsening; physical feasibility unknown |
| robust (bare) / confidence | `ROBUST_TO_TRANSFORMED_RANGE`, a deterministic label on a non-recalibrated transformed range |
| overload risk / probability | not available; v1 produces no probability |

### 24.2 Additional forbidden claims inherited from the accepted chain

- no queue, backlog, or clearance-time trajectory;
- no capacity, occupancy, bed, or staffing simulation;
- no Monte Carlo or joint predictive probability;
- no registration-shock propagation into `cohort_hospitalizations`;
- no model promotion; decision-alternative evidence never enters the model registry and cannot promote a predictive
  model;
- no scenario benefit score.

---

## 25. Known structural limitations of v1

Recorded so that no reader mistakes an artefact of the accepted evidence for a property of reality.

1. **The transfer is accounting on a forecast, not modelled patient movement.** Moving expected registrations
   between hospitals does not model referral behaviour, transport, clinical appropriateness, or acceptance.
2. **The receiver threshold comparator is unchanged.** `T_j(t)` was estimated without the synthetic flow
   (section 7.2). No threshold is re-estimated.
3. **Registrations do not propagate to hospitalizations.** `cohort_hospitalizations` is untouched by construction,
   so a transfer's implied admission, occupancy, or bed consequences are not modelled at all. Registrations and
   cohort hospitalizations are distinct targets, and the accepted chain contains no validated propagation between
   them.
4. **Zero-threshold binding cells force `phi_min = 1.0`.** The accepted thresholds contain exactly-zero supported
   values, and the fixed materiality rule is evaluated only on the entity's severity evidence cell, so materially
   eligible donors can still carry zero-threshold binding cells at other horizons. Expect a non-trivial share of
   units to demand the entire donor series, and therefore to abstain with `TRANSFER_BUDGET_INSUFFICIENT` or
   `RECEIVER_BLOCKED` on the lower budget rungs (section 21.5 item 7 makes this measurable).
5. **Zero-threshold receiver cells can bind immediately or be range-masked.** A baseline `NORMAL` cell with `T = 0`
   can force `phi_max = 0` and immediate `RECEIVER_BLOCKED`. For baseline `ELEVATED` or `HIGH`, the outcome depends
   on the accepted higher-rank sensitivity predicates; missing range evidence can make feasibility artificially
   permissive and therefore triggers `receiver_range_masking_present`, `RANGE_LIMITED`, and
   `RANGE_EVIDENCE_INCOMPLETE`.
6. **Missing range evidence relaxes the receiver constraint.** See section 10.4. Receivers with unavailable
   calibrated ranges will appear more tolerant; this is missing evidence, not tolerance.
7. **Clearing central exceedance need not clear the donor's severity or Inbox membership.** See section 6.4.
8. **A large share of accepted hospital/profile registration forecasts are fallback-supported.** The accepted primary
   Inbox is roughly one third fallback/limited-history. Both donor and receiver tiers must therefore be reported
   separately; the `DIRECT_SUPPORTED` population is materially smaller than the full Inbox.
9. **Registration history is short.** The accepted chain rests on a 90-day registration history and a 56-day
   origin-legal threshold window; nothing in v1 extends it.
10. **Full verification is expensive.** See section 12.5. The shortlist bound is a real constraint on coverage and
   MUST be reported.
11. **Inherited 6B.3 P2 caveats apply unchanged**, including the calibrated-vocabulary reason codes, the
    zero-threshold knife edge, and the fact that `deterministic_synthetic_inputs` describes the specifications, not
    the data.

---

## 26. Relationship to the accepted architecture

- 6B.4 v1 is an offline, retrospective `EVALUATION` capability. It implements no persistence, API, UI, or live
  scoring, and makes no serving claim.
- It consumes accepted artifacts through verified immutable checkpoints and artifact hashes, exactly as 6B.3 does.
  Decision-alternative evidence never enters `ModelRegistry`.
- It respects ADR 0003 (ML runtime boundary) and ADR 0005 (candidate-independent serving semantics): the backend
  never runtime-imports ML implementation, and the output contract is candidate-independent.
- Its output objects are **not** serving objects. Any future serving exposure requires a reviewed adapter, a
  legal-origin scoring mode, and its own ADR, and would have to strip retrospective evaluation labels exactly as the
  6B.2D contract requires.
- Model promotion and operational action remain human-controlled. Nothing in v1 acts.

---

## 27. Status

```text
6B.4  Constrained Decision Alternatives Engine v1
Status: IMPLEMENTED / REAL-DATA ACCEPTANCE PENDING
Accepted: 2026-09-20
Decision record: ADR 0006 (Accepted)
Implementation: COMPLETE; independent code review pending
Accepted run: NONE
Artifacts: NONE
```

Acceptance basis: independent science/architecture audit, corrective specification passes, final targeted review
PASS, all known P0/P1 findings resolved.

The offline runtime and fixture verification now exist. No accepted real-data run, backend/API integration, live
serving, or operational feasibility exists. Specification acceptance and implementation do not constitute
real-data acceptance. 6B.4 is not CLOSED.
