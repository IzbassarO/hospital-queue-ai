# ADR 0006: Use exact constrained decision alternatives over the accepted scenario surrogate instead of autonomous routing or a general-purpose solver

Status: Accepted
Date: 2026-09-20
Acceptance date: 2026-09-20
Owners: BizAI

## Acceptance note

The final independent review of this ADR and `docs/decision-alternatives-6b4.md` returned PASS with no P0 and no
P1 findings; all previously raised P0/P1 findings are resolved. This accepts the **specification only**: the
algebraic-minimum formulation with safe upward binary64 certification (`ALGEBRAIC_MINIMUM_CERTIFIED_UPWARD_FLOAT64`,
no downward tightening below the algebraic minimum), the constraint taxonomy, the contract, and the acceptance
protocol. Runtime implementation has not started; no configuration file, optimizer code, accepted run, or real-data
result exists, and 6B.4 is not closed.

## Context

Steps 6B.2 and 6B.3 are closed. The accepted chain produces, at fixed legal origins, hospital/profile registration
central forecasts with calibrated level-local ranges, exact bottom-up central hierarchy, origin-legal
`historical_flow_proxy_v1` thresholds, a five-state pressure severity, a fixed product materiality rule, a
deterministic lexicographic Signals Inbox, and — from 6B.3 — a deterministic, non-causal Forecast Stress-Test Engine
whose `inflow_transfer` lever moves a fraction of one hospital/profile's synthetic expected registrations to another
hospital in the same profile, conserving the profile/date total within `1e-9` and declaring
`feasibility = UNKNOWN`, `capacity_checked = false`, `causal_effect_claimed = false`.

Step 6B.4 was named "Constrained Optimizer / Decision Alternatives". The obvious product reading — an AI that
recommends where to route patients — is not supportable by this evidence. The project has:

- no physical capacity, staffed-bed, occupancy, or census data;
- no accepted refusal-flow forecast and no identified intervention;
- no customer decision on allowed operational actions, receiver eligibility, profile compatibility, geography,
  referral permissions, or approval workflow;
- short registration history, fallback-supported hospital/profile forecasts, and supported zero thresholds, as
  durably recorded in the accepted evidence documentation;
- independent review evidence (not a repository-native accepted artifact) that rejected the queue-accounting
  alternative and concluded **PROCEED WITH RESTRICTED SCOPE**. This ADR records the resulting scope decision, not
  the review's ephemeral scratch measurements.

Two failure modes were therefore both live. Overclaiming: presenting an optimizer output as an operational routing
recommendation, implying capacity, feasibility, causal benefit, or improved patient outcomes. Over-engineering:
introducing a MILP/CP-SAT solver dependency, a weighted objective, and a learned or scored recommender to solve a
problem whose accepted evidence does not yet support any of those degrees of freedom.

A decision was needed on the capability's name, its mathematical formulation, its constraint taxonomy, its
algorithm, and its output semantics — before implementation.

## Decision

Adopt [`../decision-alternatives-6b4.md`](../decision-alternatives-6b4.md) as the normative 6B.4 v1 specification,
with the following decisions.

1. **Capability and name.** The capability is the **Constrained Decision Alternatives Engine v1**. It generates
   human-reviewed mathematical alternatives over the accepted scenario surrogate. The names "AI recommender",
   "routing optimizer", "autonomous routing", and "capacity optimizer" are rejected for it.

2. **Canonical unit.** One optimization problem is one accepted forecast origin × `REGISTRATIONS` × one profile ×
   one selected donor hospital/profile signal × candidate same-profile receiver hospitals. There is no patient-level
   decision unit.

3. **Decision variable.** One scalar transfer fraction `phi ∈ [0,1]` applied across the 1–14 day horizon, with
   `c'_i(t) = (1 − phi)·c_i(t)` and `c'_j(t) = c_j(t) + phi·c_i(t)`, same profile, same origin, same target date.
   Expected registrations remain continuous expected counts and `phi` is never discretized into patient counts.

4. **Objective.** Minimize `phi · Σ_t c_i(t)` — total synthetic expected registrations moved. No severity score, no
   `HIGH` count, no Inbox count, no waiting time, no refusal, no clinical outcome, no learned score, and no weighted
   composite is minimized or traded against it. Severity states are constraints or diagnostics, never utility.

5. **Donor goal.** `CENTRAL_EXCEEDANCE_CLEARED` — the scenario central no longer exceeds the historical-flow
   threshold on the binding donor horizon cells. Donors are materially eligible primary-Inbox `REGISTRATIONS`
   signals with supported thresholds and a non-empty central-exceedance set; `WATCH`-only and range-driven-only
   signals are forbidden as targets. Direct-supported donors are the primary evidence tier; fallback/limited-history
   donors may be evaluated only as a separately labelled lower tier; unsupported donors are forbidden. Binding
   cells are supported by definition; unsupported non-binding horizons remain explicitly unsupported, and the donor
   goal applies only to the supported binding set rather than requiring all 14 donor horizons to be supported.

6. **Receiver constraint.** `NO_WORSE_HISTORICAL_FLOW_PROXY_STATE` — for every affected horizon the scenario
   `PressureSeverity` of the receiver must not exceed its baseline `PressureSeverity`, using the accepted 6B.3
   scenario sensitivity semantics, evaluated on **raw** severity without the product materiality floor. It is not a
   capacity constraint, not a bed constraint, and not an operational feasibility proof. Unsupported receivers are
   rejected. A baseline `NORMAL` receiver with zero threshold can bind at `phi_max = 0`; zero-threshold
   `ELEVATED`/`HIGH` behavior depends on usable range predicates, and missing range evidence is disclosed as masking
   rather than treated as complete evidence.

7. **Algorithm: exact breakpoint enumeration, no solver.** The receiver's per-cell severity rank is monotone
   non-decreasing in `phi` and the donor's is monotone non-increasing, so the donor-goal set is the closed interval
   `[phi_min, 1]`, the receiver no-worse set is the closed interval `[0, phi_max]`, and the strictly increasing
   objective is minimized exactly at

   `phi_min = max over binding cells t of ( 1 − T_i(t)/c_i(t) )`.

   Receiver breakpoints are enumerated exactly per baseline severity state. No MILP, CP-SAT, LP, grid search,
   greedy search, metaheuristic, or learned policy is used, and no solver dependency is added. The published
   fraction is the **algebraic minimum with safe upward binary64 certification**. Algebraic bounds are certified in
   their safe directions before comparison: the donor lower bound upward, and receiver and policy upper bounds
   downward. The chosen donor candidate may then move only upward under a bounded `nextafter` guard and is rechecked
   against donor, receiver, certified upper-bound, budget, domain, and conservation constraints. It is emitted as
   `ALGEBRAIC_MINIMUM_CERTIFIED_UPWARD_FLOAT64`, with 17 significant decimal digits plus a hexadecimal float. Guard
   exhaustion yields `PHI_CERTIFICATION_FAILED`. Donor binding ties use the smallest horizon. Strict predicates
   require the guard; downward tightening is not part of the optimization semantics because rounding of `(1 − phi)`
   cannot justify a fraction below the exact algebraic boundary. The donor lower-bound check therefore uses exact
   rational comparison of the represented inputs, or an equivalent safe directed-rounding method, in addition to
   recomputation at the published value.

8. **Central case with a mandatory sensitivity-range companion and orthogonal evidence axes.** The decision basis is `CENTRAL_CASE`. `WATCH`
   relief is not optimized. Every candidate additionally reports `SENSITIVITY_RANGE_CASE` with a three-valued
   deterministic label (`ROBUST_TO_TRANSFORMED_RANGE`, `NOT_ROBUST_TO_TRANSFORMED_RANGE`,
   `RANGE_EVIDENCE_INCOMPLETE`). The range is not recalibrated and carries no probability, confidence level,
   coverage guarantee, or joint distribution. This is never called probabilistic robust optimization. Forecast
   support (`DIRECT_SUPPORTED` / `FALLBACK_LIMITED`) and receiver range evidence (`COMPLETE` / `RANGE_LIMITED`) are
   independent. Range masking implies `RANGE_LIMITED` and `RANGE_EVIDENCE_INCOMPLETE`; the result may be published
   with disclosure after full verification but is excluded from the primary direct/complete acceptance cohort.
   Contract vocabulary is explicitly normalized: source `registrations`, `direct_supported`, and
   `fallback_or_limited_history` map to `REGISTRATIONS`, `DIRECT_SUPPORTED`, and `FALLBACK_LIMITED`; usable complete
   range evidence and missing/masked range evidence map to `COMPLETE` and `RANGE_LIMITED`.

9. **Two layers.** A fast exact evaluator over the donor/receiver daily cells produces internal candidate evidence only, whose claimed fields exclude
   Inbox rank, materiality, hierarchy diagnostics, explanation, and complete scenario output; then full 6B.3 scenario
   verification for shortlisted internal candidates, which establishes exact hierarchy, entity aggregation, materiality,
   complete Inbox semantics, deterministic explanation, and final differences. A mandatory test proves the two agree
   on every claimed field at tolerance `1e-9`. Only `VERIFIED_FULL_ENGINE` objects may enter the public
   `DecisionAlternativeSet.alternatives` array; shortlist drops and verification failures remain separate
   non-alternative evidence records.

10. **Reuse the accepted lever unchanged.** Full verification runs the accepted `inflow_transfer` lever under a
    `region_profile` scope with the certified fraction. **No accepted 6B.3, 6B.2C, or 6B.2C-2 code path is modified
    by 6B.4 v1**, and no new lever or scenario classification is introduced.

11. **Output is a set of fully verified alternatives, never a recommendation.** A `DecisionAlternativeSet` contains
    zero or more `DecisionAlternative` objects, all with `verification_state = VERIFIED_FULL_ENGINE` and non-null
    verification-only fields. `recommended_action`, `best_hospital`, and `optimal_patient_route` are forbidden
    field names; "optimal" is illegal without a mathematical qualifier; the approved phrase is
    `minimum_transfer_under_stated_constraints`. The system does not choose among the alternatives.

12. **Pareto filtering only, then deterministic display order.** Three transparent dimensions —
    `total_synthetic_flow_moved` (min), `receiver_worst_severity_after` (min), `receiver_min_central_headroom` (max)
    — with dominance evaluated within one canonical unit and within one
    `(forecast_support_tier, receiver_range_evidence)` stratum. There is no weighted
    scalarization. The display order (direct before fallback, smaller flow, lower receiver severity, larger headroom,
    stable receiver id) is a reproducibility device and is not a claim of real-world superiority.

13. **Constraint taxonomy is explicit and separated** into scientific hard constraints, product policy (including
    `SAME_REGION`, a policy not a fact), user-configurable policy budgets (`max_transfer_fraction`,
    `max_total_synthetic_transfer`, `eligible_receiver_ids`, `geographic_scope`), and missing-data constraints. A
    configurable transfer cap is a **policy budget, not physical capacity**, and no such value is ever inferred from
    data.

14. **Abstention is a valid result.** `NO_ELIGIBLE_RECEIVER`, `DONOR_CENTRAL_RELIEF_INFEASIBLE`,
    `TRANSFER_BUDGET_INSUFFICIENT`, `RECEIVER_BLOCKED`, `INSUFFICIENT_SUPPORT`, `UNSUPPORTED_SIGNAL`, and
    `NO_NON_DOMINATED_ALTERNATIVE` are defined, plus v1 extensions. Every returned alternative carries the standing
    qualifier `PHYSICAL_FEASIBILITY_UNKNOWN` / `NOT_PHYSICAL_CAPACITY_VALIDATED`. Constraints are never silently
    relaxed.

15. **Retrospective evaluation only.** `execution_mode = EVALUATION`, `serving_claim = false`,
    `human_review_required = true`, `capacity_checked = false`, `causal_effect_claimed = false`. No persistence, API,
    UI, migration, or live scoring is introduced.

This ADR is **Accepted**. It accepts the specification only; runtime implementation has not started. The 6B.4
status is **SPEC ACCEPTED / IMPLEMENTATION NOT STARTED**.

## Dependency rules

- 6B.4 implementation MUST NOT modify `ml/hqai_ml/flow_forecast/scenario.py`, `pressure.py`, or
  `prioritization.py`, nor any accepted configuration, threshold, calibration, severity, materiality, or ranking
  rule. It consumes them.
- 6B.4 MUST NOT add a solver, constraint-programming, metaheuristic, or optimization-framework dependency to
  `requirements.txt` or `pyproject.toml`. v1 is closed-form.
- 6B.4 MUST NOT introduce a learned model, scoring model, ranker, or LLM into the alternative-generation or
  explanation path. Explanation is deterministic and template-driven.
- 6B.4 evidence MUST NOT enter `ModelRegistry` and cannot promote a predictive model, exactly as 6B.3 evidence
  cannot.
- The backend MUST NOT runtime-import 6B.4 implementation (ARCH001/ADR 0003 unchanged). No endpoint, Pydantic class,
  table, or migration is authorized by this ADR.
- Output semantics MUST stay candidate-independent per ADR 0005: no model family, artifact column layout, fold,
  candidate, or training parameter in public fields.
- A future `physical_capacity_provider_v1` MUST NOT be introduced by renaming `historical_flow_proxy_v1`; it
  requires real capacity data and independent review.
- Retrospective evaluation labels remain non-serving-eligible; any future serving exposure requires a reviewed
  adapter, a legal-origin scoring mode, and its own ADR.

## Alternatives considered

- **Autonomous routing / an AI recommender that selects a transfer.** Rejected. No capacity, occupancy, staffing,
  profile-compatibility, referral-permission, or allowed-action evidence exists; no intervention is identified; and a
  single selected action would present an unvalidated operational instruction. Human review is not a disclaimer on
  top of a recommendation — the absence of a recommendation is the decision.
- **A general MILP or CP-SAT formulation.** Rejected for v1. The problem is one continuous variable with a strictly
  increasing linear objective over a single closed interval; the optimum is a closed-form breakpoint. A solver would
  add an external dependency, cross-platform non-determinism, tolerance semantics weaker than the exact algebra, and
  an opaque certificate, for no gain. Even single-donor multi-receiver allocation stays a linear program; a MILP is
  justified only by genuinely discrete structure (receiver cardinality limits, per-pair activation costs or minimum
  sizes, integer capacity units, count-based constraints needing indicator variables, either/or admissibility).
- **Grid search or greedy search over `phi`.** Rejected. Both are inexact, both hide the binding cell, and both make
  the published fraction an artefact of step size rather than of the accepted severity rule.
- **A weighted multi-objective score (severity relief, flow moved, headroom).** Rejected. The weights would be
  unvalidated policy presented as science, and the accepted chain already refuses to collapse support and uncertainty
  into one score. Pareto filtering plus a deterministic display order keeps every trade-off visible.
- **Minimizing a severity or `HIGH`-count objective.** Rejected. Under the accepted rule, `HIGH` transitions are
  dominated by zero-threshold sparse cells (the accepted 6B.3 P2 knife-edge finding), so a count objective would
  optimize a knife edge and not an operational quantity. Counting also requires indicator variables and therefore a
  MILP.
- **Optimizing `WATCH` relief or the sensitivity range.** Rejected. The scenario range is a transformed,
  non-recalibrated deterministic interval with no coverage guarantee; optimizing against it would present an
  uncalibrated bound as a risk budget. It is reported as a mandatory companion instead.
- **A queue/backlog-clearance objective.** Rejected based on independent review evidence, not a repository-native
  accepted measurement. The durable reasons are that refusals are not forecast, the queue identity is not accepted
  predictive science, and 6B.3 already forbids a queue trajectory as an output.
- **Patient-count (integer) transfers.** Rejected. Central forecasts are continuous expected counts; discretizing
  them would manufacture a patient-level decision object that the evidence does not support and would turn the
  problem into an integer program for presentational reasons only.
- **Applying the product materiality floor to receiver harm.** Rejected. It would hide real modelled worsening on
  low-volume receiver cells behind a product triage rule. Materiality gates donor search visibility only.
- **A new scenario lever for optimizer-driven transfers.** Rejected as unnecessary and as a scope violation: the
  accepted `inflow_transfer` lever already realizes the exact v1 transform, so v1 changes no accepted code.
- **Deferring 6B.4 entirely until capacity data exists.** Rejected as too strong. The restricted formulation
  produces reviewable, exactly verifiable mathematical evidence, makes the missing-data boundary explicit rather than
  implicit, and gives the customer conversation a concrete artifact — provided nothing in it is presented as an
  operational recommendation.

## Consequences

### Positive

- The mathematical claim is exact and closed-form, so it is fully reproducible and independently checkable by hand.
- No accepted code changes, so 6B.3/6B.2C scientific identities remain intact and the accepted evidence chain is
  untouched.
- No new runtime dependency and no solver non-determinism.
- The overclaim surface is closed by construction: forbidden field names, a vocabulary substitution table, standing
  feasibility qualifiers, and `capacity_checked = false` on every object.
- The two-layer design gives cheap exactness for search and full accepted-engine semantics for anything displayed,
  with a mandatory equality test between them.
- Missing-evidence artefacts are surfaced rather than hidden: range-masking disclosure, zero-threshold binding cells,
  and separate reporting on forecast-support and range-evidence axes.
- A future capacity provider, multi-receiver allocation, or LP/MILP extension can be added without redesigning the
  contract.

### Negative

- v1 answers a narrow question. It cannot say whether a transfer is possible, permitted, or beneficial, and some
  readers will find that unsatisfying relative to the words "optimizer" and "recommendation".
- Because `phi_min` is receiver-independent, every alternative in one canonical unit moves the same total flow, so
  within a unit the alternatives differ only in receiver-side impact. The set is deliberately less decisive than a
  ranked recommendation list.
- Zero-threshold binding cells force `phi_min = 1.0`, so a material share of units will abstain on the lower budget
  rungs. Abstention rates will be visible and may look like low capability.
- Full 6B.3 verification is expensive, so displayed coverage is bounded by a precommitted shortlist.
- The `SAME_REGION` policy and every budget value are placeholders that must be revisited once customer rules exist.
- A single scalar `phi` cannot express partial-horizon or per-day transfers, and multi-receiver allocation is out of
  scope.
- The required field name `optimizer_contract_version` sits in tension with the rejected "optimizer" naming; it is
  retained for contract-key stability and is explicitly not a capability claim.

## Migration

1. Independent review of `docs/decision-alternatives-6b4.md` and this ADR. No code until both are accepted.
2. On acceptance, move this ADR to Accepted and add `ml/configs/decision_alternatives.yaml` with the normative keys
   of specification section 17, including the precommitted donor cohort `N`, origins, budget ladder, and shortlist
   bound.
3. Implement the fast exact evaluator plus the constraint, abstention, Pareto, and display layers in a new module
   under `ml/hqai_ml/flow_forecast/`, importing the accepted pressure/prioritization/scenario functions without
   modifying them.
4. Implement full 6B.3 verification as a thin adapter that constructs the accepted `inflow_transfer` specification
   and compares claimed fields at tolerance `1e-9`.
5. Add the acceptance-invariant tests of specification section 20, including synthetic fixtures that exercise
   `phi = 0` identity, conservation, monotonicity, zero-threshold binding cells, range-unavailable receivers,
   every abstention code, and the forbidden-lexicon checks.
6. Precommit the real-data configuration, then execute one real-data run and report exactly the metrics of
   specification section 21 — including abstention rates and required zero receiver worsening — for independent
   acceptance.
7. Only after acceptance may any serving, persistence, API, or UI exposure be considered, and only through a
   separately reviewed adapter and ADR.

No step combines implementation with a change to accepted science, and no step introduces a solver.

## Verification

- Specification section 20 invariants 1–35 become tests; each failure is blocking, including the rule that every
  published alternative is `VERIFIED_FULL_ENGINE`.
- The fast-evaluator/full-engine equality test at tolerance `1e-9` over the claimed-field set of specification
  section 12.1 is mandatory.
- Forbidden field names, the forbidden lexicon, and the vocabulary substitution table are enforced by test over
  contract keys, artifact columns, artifact values, and explanation text.
- Dependency tests assert that no solver/optimization framework and no LLM client is added.
- Architecture checks (ARCH001–ARCH005) and `make audit` continue to run unchanged; ARCH001 keeps the backend from
  importing 6B.4 implementation.
- Determinism: identical specification and inputs produce byte-identical scientific output and identical hashes,
  with timestamps excluded from every identity.
- Acceptance requires the real-data protocol of specification section 21, split by both evidence axes, with receiver
  worsening count `= 0` and a full-engine verification rate of `100%` for shortlisted internal candidates.
- No model is promoted and no accepted scientific result is changed by adopting this decision.

## Revisit when

Revisit when any of the following becomes available and independently reviewed: real physical capacity, staffed
beds, occupancy or census data; agreed allowed operational actions, receiver eligibility, profile compatibility,
geography, or referral permissions; an accepted refusal-flow forecast; an identified intervention permitting causal
statements; materially longer registration history; validated joint uncertainty; or a multi-receiver /
capacity-aware formulation whose discrete structure genuinely requires an LP or MILP. Any of these requires a new
ADR; none of them may be introduced by renaming an existing provider or relabelling an existing constraint.
