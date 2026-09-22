# Constrained Decision Alternatives Engine implementation

Status: **CLOSED**

The Step 6B.4 offline runtime implements the accepted
[`decision-alternatives-6b4.md`](decision-alternatives-6b4.md) contract without changing the accepted scenario,
pressure, or prioritization modules. ADR 0006 remains Accepted. This implementation is retrospective `EVALUATION`
only. Real-data evidence from `decision-alternatives-6b4-real-v3` was accepted with verdict
**ACCEPT WITH P2 ONLY**; Step 6B.4 is closed.

## Runtime architecture

- `ml/hqai_ml/flow_forecast/decision_alternatives.py` owns configuration validation, donor and receiver
  eligibility, exact rational bounds, directed binary64 certification, the local evaluator, evidence-stratified
  Pareto filtering, shortlisting, full-engine agreement, public contract construction, deterministic identities,
  and abstention.
- The local evaluator operates on exactly the donor/receiver 28 registration cells. It calls the accepted
  `transform_sensitivity_range`, `reevaluate_daily_pressure`, and `severity_for_row` implementations. It does not
  compute Inbox rank, hierarchy diagnostics, materiality, or a public explanation.
- Every shortlisted internal candidate is verified with the unchanged accepted `evaluate_scenario` engine using
  its `inflow_transfer` lever and `region_profile` scope. The verification input retains the full hospital context
  for the canonical origin while avoiding recomputation of unrelated origins.
- Only `VERIFIED_FULL_ENGINE` objects enter `alternatives`. Shortlist drops and verification failures use separate
  evidence records.
- `ml/pipelines/decision_alternatives.py` verifies immutable accepted source checkpoints, applies the precommitted
  cohort and budget ladder, and writes only ignored evidence artifacts under `artifacts/decision_alternatives/`.

## Numeric certification

Finite binary64 inputs are interpreted as their exact rational values with `Fraction.from_float`. Donor lower
bounds are compared as exact rationals. Starting from `float(phi_min_alg)`, certification tests the current value
first and moves only with `nextafter(phi, +infinity)` when required. The implementation never tightens the selected
donor fraction downward. Receiver and policy upper bounds start from their binary64 encodings and move only toward
zero until the exact upper-bound comparison and applicable constraint pass. The shared guard counts upward donor
corrections, and the final permitted candidate is tested.

The final certification recomputes the donor goal, receiver raw-severity no-worse constraint, certified receiver and
policy bounds, domain, and per-horizon/total conservation. Replay metadata includes the float, 17-significant-digit
decimal, hexadecimal representation, and upward step count.

Full verification is memoized per run by origin, phase, target, region, profile, donor and receiver identities,
certified fraction hexadecimal value, scenario contract, all accepted upstream run identities, scenario scientific
identity, decision-config identity, and code identity. A policy-budget rung is intentionally absent from this key
because it does not change the transfer scenario. Successful and failed verification outcomes are both cached; a
failed verification can never become successful through another rung.

The cache does not retain `ScenarioEvaluation` or any pandas frame. After fast/full comparison, it stores only a
frozen record containing canonical JSON for the timestamp-free scenario scientific payload and verification-only
fields, the scientific-output SHA-256, success/failure fields, and a fingerprint of the fast payload. A cache hit
must match that fingerprint. Verification daily/anomaly slices are constructed lazily only after a cache miss and
once per alternative-set evaluation, so an all-hit budget rung allocates no verification slice.

## Evidence and safety semantics

Donors must be materially eligible registration rows from the primary Inbox with supported entity evidence,
`ELEVATED` or `HIGH` displayed severity, an enabled support tier, and at least one supported central exceedance.
`WATCH`-only and range-driven-only signals abstain. Receivers must be distinct, same-profile, same-region,
same-origin series with exactly one aligned cell for horizons 1–14 and supported thresholds on every affected
horizon.

Receiver harm uses raw accepted severity with no materiality floor. Missing usable receiver range evidence remains
orthogonal to forecast support and produces `RANGE_LIMITED`, `receiver_range_masking_present=true`, and
`RANGE_EVIDENCE_INCOMPLETE`; it cannot enter the primary direct/complete acceptance stratum.

Every public alternative fixes human review to true; capacity, causal effect, range recalibration, coverage, and
serving claims to false; and physical feasibility to `NOT_PHYSICAL_CAPACITY_VALIDATED`.

Acceptance reporting preserves pooled unit-level measures but separately reports the direct-donor denominator and
its `DIRECT_SUPPORTED + COMPLETE` numerator, the fallback-donor denominator and numerator, range-limited unit and
alternative rates, and all four joint evidence strata (including explicit zero counts). Receiver rejection rows
never become acceptance denominators. Dry-plan receiver counts apply the same-region, same-profile and optional
allow-list scope; unavailable cheap-layer counts and all derived verification counts are explicitly labelled as
not computed or upper bounds.

Before a non-plan run begins, selected donors must join to at least one expected registration daily unit. A cohort
for which no selected unit joins fails as `DONOR_DAILY_INPUT_JOIN_FAILED`; scientifically valid abstentions after a
valid join remain normal evidence outcomes.

## Verification status

Synthetic unit and integration fixtures exercise the 35 accepted invariants where applicable, including algebraic
minimums, directed rounding, zero thresholds, all receiver baseline severity states, raw receiver harm, range
masking, conservation, evidence axes, budgets, Pareto behavior, deterministic output, abstention, fast/full
agreement, forbidden public fields, and the rule that no internal or failed candidate becomes an alternative.

Accepted real-data evidence:

- run: `decision-alternatives-6b4-real-v3`;
- scientific identity: `fb7410fa230d4c252c58cbbe98e4ccfbe45102800d5422ba45f8ce79d788a7a8`;
- verdict: **ACCEPT WITH P2 ONLY** (P0: none; P1: none);
- 115 donor units and 460 alternative sets;
- zero full-verification failures and zero receiver worsening;
- 100% full-verification success;
- primary `DIRECT_SUPPORTED + COMPLETE` rate: 29/80 (36.25%) at budget 0.25 and 46/80 (57.5%) at budget 1.00;
- 256 unique full verifications and 174 cache reuses;
- runtime approximately 24,059 seconds and peak RSS 2154.34375 MiB.

Non-blocking P2s retained with the acceptance evidence:

1. laptop runtime was approximately 6.7 hours;
2. peak RSS was slightly above the nominal 2 GiB memory budget;
3. the shortlist bound dropped 4 alternatives at budget 0.25 and 6 at budget 1.00.

Failed evidence remains part of the record and is not accepted evidence:

- `decision-alternatives-6b4-real-v1` — **FAILED EVIDENCE** because real parquet `reason_codes` materialized as an
  array-like value whose boolean truthiness was ambiguous;
- `decision-alternatives-6b4-real-v2` — **FAILED EVIDENCE** because raw `float.hex()` containing `+` was embedded in
  `ScenarioSpec.scenario_id` and violated its identifier contract.

The accepted capability remains retrospective mathematical decision alternatives for human review. Its fixed
boundaries are `execution_mode = EVALUATION`, `autonomous_action = false`, `human_review_required = true`,
`capacity_checked = false`, `causal_effect_claimed = false`, and `serving_claim = false`; physical feasibility is
not validated, and neither model-registry nor automatic promotion occurs.

The direct-supported primary cohort and fallback/limited secondary-evidence cohort have separate precommitted
limits (`top_n_primary_donors` and `top_n_fallback_donors`). Receiver exclusions caused by the v1 same-region policy
or the configured allow-list use the documented extension codes `RECEIVER_OUTSIDE_SAME_REGION_POLICY` and
`RECEIVER_NOT_ALLOW_LISTED`.
