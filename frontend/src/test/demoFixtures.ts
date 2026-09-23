/**
 * Guided-journey fixtures shaped like the real published responses of the deterministic demo signal
 * (rank 1 at the explicit final-test origin). Values are copied from the live publication; nothing is invented.
 */
import type {
  AlternativeSetResponse,
  AlternativeSetSummaryResponse,
  ModelAssuranceCapabilityResponse,
  OperationalForecastResponse,
  OperationalRegionResponse,
  OperationalSignalResponse,
  ReviewOverviewResponse,
  SignalDecisionAlternativesResponse,
  SignalExplanationResponse,
  SignalStressTestResponse,
} from "../api/generated";
import { fixtures } from "./mockApi";
import * as f from "./operationalFixtures";

export const DEMO_SIGNAL_ID = "cc50965694cb0b6862928df5";
export const ORIGIN = "2025-03-17";
export const OPERATIONAL_IDENTITY = f.identity;
const source = {
  run_id: "flow-scenario-6b3-real-v1",
  scientific_identity_sha256: "4".repeat(64),
  artifact_sha256: "5".repeat(64),
  dataset_identity_sha256: "6".repeat(64),
  config_identity_sha256: "7".repeat(64),
  code_identity_sha256: "8".repeat(64),
};
const provenance = {
  flow_scenario: source,
  decision_alternatives: {
    ...source,
    run_id: "decision-alternatives-6b4-real-v3",
  },
};

export const demoSignal: OperationalSignalResponse = {
  ...f.signal,
  signal_id: DEMO_SIGNAL_ID,
  series_id: "hp:000V:391",
  origin: ORIGIN,
  org_code: "000V",
  region_code: "39",
  profile_code: "391",
  inbox_rank: 1,
  severity: "HIGH",
  headline: "High flow pressure expected within 1 day.",
  concise_reason:
    "Calibrated lower forecast bound exceeds the hospital/profile historical high-flow threshold.",
  materiality_status: "materiality_rule_not_triggered",
  threshold_value: 1.0,
  threshold_status: "supported",
  forecast_value: 5.917120202733519,
  uncertainty_lower: 1.373309576901387,
  uncertainty_upper: 23.674832462743403,
  first_crossing_date: "2025-03-18",
  lead_time_days: 1,
  observed_anomaly_status: "none",
  data_freshness: ORIGIN,
  reason_codes: ["CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD"],
  evidence_facts: [
    "Forecast uses direct model support.",
    "Calibrated uncertainty is available.",
    "Displayed severity evidence is horizon 1 on 2025-03-18.",
    "Accepted publication view: top_priority_all.",
  ],
  limitations: [
    "only 90 days of registration history; no annual-seasonality claim",
    "Human review required; no autonomous routing or causal effect claim.",
  ],
};
export const regionSignals: OperationalSignalResponse[] = [
  demoSignal,
  {
    ...demoSignal,
    signal_id: "f324c45c7aebb42f510dc327",
    series_id: "hp:ZH60:071",
    org_code: "ZH60",
    profile_code: "071",
    inbox_rank: 3,
    forecast_value: 1.08,
  },
  {
    ...demoSignal,
    signal_id: "a05176c661034ba9715179d5",
    series_id: "hp:22VJ:031",
    org_code: "22VJ",
    profile_code: "031",
    inbox_rank: 9,
    severity: "ELEVATED",
    headline: "Elevated flow pressure expected within 12 days.",
    forecast_value: 1.43,
  },
];
const CENTRAL = [
  5.917, 5.921, 5.187, 2.321, 0.723, 0.723, 2.033, 1.652, 5.887, 5.152, 5.736,
  0.723, 0.723, 8.765,
];
const LOWER = [
  1.373, 1.453, 1.35, 0, 0, 0.15, 0, 0, 1.24, 1.2, 1.3, 0, 0.15, 1.43,
];
const UPPER = [
  23.675, 23.541, 23.52, 21.49, 3.69, 3.42, 15.82, 20.52, 23.72, 23.64, 24.66,
  3.93, 3.56, 30.52,
];
export const DATES = Array.from({ length: 14 }, (_, i) => `2025-03-${18 + i}`);
export const demoForecast: OperationalForecastResponse[] = DATES.map(
  (date, i) => ({
    ...f.forecast,
    series_id: "hp:000V:391",
    origin: ORIGIN,
    target_date: date,
    horizon: i + 1,
    org_code: "000V",
    region_code: "39",
    profile_code: "391",
    central_value: CENTRAL[i],
    raw_quantiles: {
      p10: LOWER[i],
      p50: CENTRAL[i],
      p90: UPPER[i],
      semantics: "UNCHANGED_MODEL_EVIDENCE",
    },
    calibrated_uncertainty: {
      lower: LOWER[i],
      upper: UPPER[i],
      nominal_coverage: 0.8,
      calibration_status: "CALIBRATED",
      support_class: "direct_quantile_ml",
      calibration_version:
        "temporal-count-interval-calibration-v1-802a155f4e8c",
    },
    hierarchy_status: "bottom_up_child_unchanged",
  }),
);
export const demoOverview = {
  ...f.overview,
  snapshot: { ...f.overview.snapshot, current_origin: ORIGIN },
  regions: [
    {
      region_code: "39",
      counts: { ...f.counts, total_signals: 207, high: 60 },
    },
    {
      region_code: "61",
      counts: { ...f.counts, total_signals: 429, high: 96 },
    },
    {
      region_code: "71",
      counts: { ...f.counts, total_signals: 280, high: 30 },
    },
  ],
};
export const demoRegion: OperationalRegionResponse = {
  snapshot: demoOverview.snapshot,
  region_code: "39",
  counts: { ...f.counts, total_signals: 207, high: 60 },
  top_signals: regionSignals,
  forecast_point_count: 10640,
  available_origins: [ORIGIN],
  available_targets: ["registrations"],
};
export const demoDictionaries = {
  national_code: "KZ",
  regions: [
    { code: "39", name: "Костанайская область" },
    { code: "61", name: "Туркестанская область" },
    { code: "71", name: "г. Астана" },
  ],
  profiles: [
    {
      code: "391",
      name: "Отоларингологические для взрослых",
      is_day_hospital: false,
    },
    { code: "031", name: "Кардиологические", is_day_hospital: false },
    { code: "071", name: "Неврологические", is_day_hospital: false },
    { code: "241", name: "Патологии беременности", is_day_hospital: false },
  ],
  organizations: [
    {
      code: "000V",
      name: 'Коммунальное государственное предприятие "Костанайская областная больница" Управления здравоохранения',
      region_code: "39",
    },
    {
      code: "22VJ",
      name: 'ТОО "Костанайский областной кардиологический центр"',
      region_code: "39",
    },
    {
      code: "0FU6",
      name: 'КГП "Рудненская городская многопрофильная больница"',
      region_code: "39",
    },
    { code: "ZH60", name: "Стационар ZH60", region_code: "39" },
  ],
};
export const demoExplanation: SignalExplanationResponse = {
  ...f.explanation,
  subject: {
    ...f.explanation.subject,
    signal_id: DEMO_SIGNAL_ID,
    org_code: "000V",
    region_code: "39",
    profile_code: "391",
    inbox_rank: 1,
    origin: ORIGIN,
  },
  summary:
    "A HIGH preventive-flow signal was published for registrations using historical_flow_proxy_v1. It is an attention flag for human review, not a physical-capacity finding.",
  why_flagged: [
    "Calibrated lower forecast bound exceeds the hospital/profile historical high-flow threshold.",
    "The published first crossing date is 2025-03-18 with a 1-day lead time.",
  ],
  key_evidence: [
    {
      code: "reason_code",
      statement: "CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD",
      value: null,
    },
    {
      code: "published_evidence_fact",
      statement: "Forecast uses direct model support.",
      value: null,
    },
    {
      code: "central_forecast",
      statement: "Published central forecast value.",
      value: 5.917120202733519,
    },
    {
      code: "historical_flow_reference",
      statement: "Published historical-flow reference value.",
      value: 1.0,
    },
    {
      code: "materiality_status",
      statement: "Published materiality classification.",
      value: "materiality_rule_not_triggered",
    },
  ],
  uncertainty: {
    ...f.explanation.uncertainty,
    narrative: "The calibrated uncertainty interval is 1.37331 to 23.6748.",
    central_value: 5.917,
    calibrated_lower: 1.373,
    calibrated_upper: 23.675,
    target_date: "2025-03-18",
  },
  support: {
    ...f.explanation.support,
    narrative: "The published signal is directly supported for this series.",
  },
  limitations: [
    "Human review required; no autonomous routing or causal effect claim.",
    "historical_flow_proxy_v1 is a historical-flow count reference, not beds, occupancy, staffed capacity, confirmed physical overload, or physical feasibility.",
  ],
  suggested_review_questions: [
    "Is more recent observed information available for comparison?",
  ],
  provenance: {
    ...f.explanation.provenance,
    publication_identity_sha256: OPERATIONAL_IDENTITY,
  },
};
export const legacyCard = {
  ...fixtures.card,
  series: [
    {
      date: "2025-03-10",
      registrations: 0,
      hospitalizations: 0,
      refusals: 0,
      queue: 42,
    },
    {
      date: "2025-03-11",
      registrations: 1,
      hospitalizations: 3,
      refusals: 1,
      queue: 39,
    },
    {
      date: "2025-03-17",
      registrations: 56,
      hospitalizations: 0,
      refusals: 1,
      queue: 95,
    },
    {
      date: "2025-03-18",
      registrations: 9,
      hospitalizations: 1,
      refusals: 1,
      queue: 102,
    },
  ],
};
const scenario = (
  id: string,
  multiplier: number | null,
  share: number,
  changed = 0,
  entitiesChanged = 0,
): ReviewOverviewResponse["scenarios"][number] => ({
  scenario_id: id,
  scenario_type: multiplier === null ? "identity" : "demand_multiplier",
  classification: "SAFE_NON_CAUSAL_STRESS_TEST",
  lever_type: multiplier === null ? "identity" : "demand_multiplier",
  multiplier,
  scope_type: "all_hospitals",
  horizon_start: 1,
  horizon_end: 14,
  target: "registrations",
  uncertainty_method: "additive_central_shift_v1",
  uncertainty_label: "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE",
  coverage_guarantee: false,
  causal_effect_claimed: false,
  serving_claim: false,
  baseline_reproduction: multiplier === null ? "PASS" : null,
  network_summary: {
    daily_cells_total: 366072,
    severity_changed_count: changed,
    severity_changed_share: share,
    severity_counts: {
      HIGH: 2475,
      ELEVATED: 30199,
      WATCH: 39658,
      NORMAL: 285976,
      UNSUPPORTED: 7764,
    },
    entity_count: 26148,
    entity_severity_changed_count: entitiesChanged,
  },
  evidence_facts: [
    "Verification: boundaries=PASS; scope invariance=PASS; hierarchy coherent=True.",
  ],
  limitations: [
    "No causal identification; no capacity; no joint distribution; synthetic sensitivity bounds have no coverage guarantee.",
  ],
});
export const scenarios = [
  scenario("baseline-identity", null, 0),
  scenario("national-registrations-x0.90", 0.9, 0.01726, 6320, 1085),
  scenario("national-registrations-x1.10", 1.1, 0.08302, 30392, 3194),
  scenario("national-registrations-x1.20", 1.2, 0.10297, 37695, 4360),
];
export const reviewSnapshot: ReviewOverviewResponse["snapshot"] = {
  publication_id: "review-evidence-slice6-final-test-2025-03-17-v1",
  schema_version: "review_evidence_v1",
  contract_version: "1.0.0",
  publication_identity_sha256: "9".repeat(64),
  bundle_sha256: "9".repeat(64),
  assurance_identity_sha256: f.identity,
  operational_publication_identity_sha256: OPERATIONAL_IDENTITY,
  source_code_commit: "d".repeat(40),
  current_origin: ORIGIN,
  freshness_state: "UNKNOWN",
  publication_status: "AVAILABLE",
  generated_at: null,
  published_at: "2026-09-23T09:00:00Z",
  scenario_count: 4,
  scenario_entity_count: 10084,
  scenario_cell_count: 141176,
  alternative_set_count: 460,
  alternative_count: 430,
  source_provenance: provenance,
  limitations: [
    "Forecast stress tests are deterministic non-causal sensitivity checks of the accepted registrations forecast.",
  ],
};
export const reviewOverview: ReviewOverviewResponse = {
  snapshot: reviewSnapshot,
  scenarios,
  alternatives_summary: {
    set_count: 460,
    unit_count: 115,
    sets_with_alternatives: 172,
    alternative_count: 430,
    receiver_worsening_count: 0,
    verification_failure_count: 0,
    full_verification_success_rate: 1,
    transfer_budget_ladder: [0.05, 0.1, 0.25, 1],
    origins: ["2025-02-16", "2025-02-23", "2025-03-02", ORIGIN],
    evaluation_population:
      "115 donor units and 460 policy-budget alternative sets.",
  },
};
export const stressTest: SignalStressTestResponse = {
  snapshot: reviewSnapshot,
  signal_id: DEMO_SIGNAL_ID,
  series_id: "hp:000V:391",
  origin: ORIGIN,
  target: "registrations",
  org_code: "000V",
  region_code: "39",
  profile_code: "391",
  outcomes: scenarios.map((sc) => {
    const m = sc.multiplier ?? 1;
    const severity = m < 1 ? "ELEVATED" : "HIGH";
    return {
      scenario: sc,
      baseline_severity: "HIGH",
      scenario_severity: severity,
      baseline_inbox_rank: 1,
      scenario_inbox_rank: 1,
      baseline_central: CENTRAL[0],
      scenario_central: CENTRAL[0] * m,
      threshold_value: 1,
      absolute_delta: CENTRAL[0] * (m - 1),
      relative_delta: m - 1,
      severity_changed: m < 1,
      entered_primary_inbox: false,
      left_primary_inbox: false,
      first_crossing_date: "2025-03-18",
      lead_time_days: 1,
      materiality_status: "materiality_rule_not_triggered",
      scenario_headline:
        m < 1
          ? "Elevated flow pressure expected within 1 day."
          : "High flow pressure expected within 1 day.",
      scenario_reason:
        m < 1
          ? "Central forecast exceeds the hospital/profile historical high-flow threshold."
          : "Derived scenario sensitivity lower bound exceeds the hospital/profile historical high-flow threshold.",
      scenario_range_available: true,
      limitations: sc.limitations ?? [],
      cells: DATES.map((date, i) => ({
        target_date: date,
        horizon: i + 1,
        baseline_central: CENTRAL[i],
        baseline_lower: LOWER[i],
        baseline_upper: UPPER[i],
        baseline_severity: "HIGH",
        scenario_central: CENTRAL[i] * m,
        scenario_lower: Math.max(0, LOWER[i] + CENTRAL[i] * (m - 1)),
        scenario_upper: UPPER[i] + CENTRAL[i] * (m - 1),
        scenario_severity: severity,
        threshold_value: 1,
        threshold_status: "supported",
        scenario_uncertainty_status: "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE",
        severity_changed: m < 1,
        source_reason_code:
          "CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD",
      })),
    };
  }),
};
const state = (
  severity: "HIGH" | "ELEVATED" | "WATCH" | "NORMAL",
  scale: number,
  threshold: number,
) => ({
  displayed_severity: severity,
  max_severity_7d: severity,
  max_severity_14d: severity,
  severity_evidence_horizon: 12,
  severity_evidence_date: "2025-03-29",
  cells: DATES.map((date, i) => ({
    horizon: i + 1,
    target_date: date,
    central: (5 - (i % 4)) * scale,
    lower: 0.5 * scale,
    upper: 8 * scale,
    severity,
    threshold_value: threshold,
    threshold_status: "supported",
  })),
});
export const exampleSet: AlternativeSetResponse = {
  set_id:
    "5f9f09f664482d629e48504d15199e98a525d921399c2b76e263efee76b6a58f-1.00",
  canonical_unit_id:
    "5f9f09f664482d629e48504d15199e98a525d921399c2b76e263efee76b6a58f",
  origin: ORIGIN,
  target: "registrations",
  donor: {
    signal_id: "a05176c661034ba9715179d5",
    org_code: "22VJ",
    profile_code: "031",
    region_code: "39",
    series_id: "hp:22VJ:031",
    displayed_severity: "ELEVATED",
    priority_support_class: "direct_supported",
    materiality_status: "materiality_rule_not_triggered",
    binding_horizons: [12, 13],
    inbox_rank: 9,
  },
  budget: 1,
  abstained: false,
  abstention_codes: [],
  rejected_receiver_counts: {
    RECEIVER_OUTSIDE_SAME_REGION_POLICY: 178,
    RECEIVER_BLOCKED: 5,
  },
  receiver_candidates_considered: 184,
  receiver_candidates_eligible: 6,
  donor_minimum_transfer_fraction: 0.30291609871171393,
  shortlist_bound: 5,
  alternatives: [
    {
      alternative_id:
        "fc89547e058c61bce3d8248b15809ac0ed76d669ac4da0ef552fae7334dadb49",
      donor: {
        org_code: "22VJ",
        profile_code: "031",
        region_code: "39",
        series_id: "hp:22VJ:031",
      },
      receiver: {
        org_code: "0FU6",
        profile_code: "031",
        region_code: "39",
        series_id: "hp:0FU6:031",
      },
      transfer_fraction: 0.30291609871171393,
      transfer_fraction_certification:
        "ALGEBRAIC_MINIMUM_CERTIFIED_UPWARD_FLOAT64",
      transferred_total: 13.260999523432124,
      transferred_by_horizon: DATES.map((date, i) => ({
        horizon: i + 1,
        target_date: date,
        moved: 0.947,
      })),
      donor_severity_before: "ELEVATED",
      donor_severity_after: "WATCH",
      receiver_severity_before: "WATCH",
      receiver_severity_after: "WATCH",
      donor_binding_horizons: [12, 13],
      donor_binding_cell: { horizon: 12, threshold_value: 1 },
      receiver_binding_cell: { horizon: 3, predicate: "CENTRAL" },
      receiver_min_central_headroom: 1.1825727337248448,
      receiver_no_worse_constraint_satisfied: true,
      conservation_satisfied: true,
      budget_constraint_satisfied: true,
      source_central_goal_satisfied: true,
      verification_state: "VERIFIED_FULL_ENGINE",
      forecast_support_tier: "DIRECT_SUPPORTED",
      donor_support_class: "DIRECT_SUPPORTED",
      receiver_support_class: "DIRECT_SUPPORTED",
      receiver_range_evidence: "COMPLETE",
      sensitivity_range_result: "NOT_ROBUST_TO_TRANSFORMED_RANGE",
      feasibility_status: "NOT_PHYSICAL_CAPACITY_VALIDATED",
      capacity_checked: false,
      causal_effect_claimed: false,
      human_review_required: true,
      hierarchy_coherent: true,
      donor_inbox: {
        baseline_inbox_rank: 9,
        scenario_inbox_rank: 2272,
        baseline_severity: "ELEVATED",
        scenario_severity: "WATCH",
        entered_primary_inbox: false,
        left_primary_inbox: false,
      },
      receiver_inbox: {
        baseline_inbox_rank: 695,
        scenario_inbox_rank: 344,
        baseline_severity: "WATCH",
        scenario_severity: "WATCH",
        entered_primary_inbox: false,
        left_primary_inbox: false,
      },
      explanation_text:
        "Moving a synthetic fraction 0.30 of this hospital/profile's expected registrations to 0FU6 removes the donor's central historical-flow threshold exceedance. This is a mathematical alternative under stated constraints, requires human review, and is not an action, instruction, or recommendation.",
      non_claims: ["No real-world improvement is claimed."],
      limitations: [
        "NOT_PHYSICAL_CAPACITY_VALIDATED",
        "THRESHOLD_COMPARATOR_ASSUMPTION",
        "PHYSICAL_FEASIBILITY_UNKNOWN",
      ],
      baseline_donor_state: state("ELEVATED", 1, 8),
      scenario_donor_state: state("WATCH", 0.7, 8),
      baseline_receiver_state: state("WATCH", 1.2, 10),
      scenario_receiver_state: state("WATCH", 1.5, 10),
    },
  ],
  verification_failure_count: 0,
  scientific_output_sha256: "a".repeat(64),
  execution_mode: "EVALUATION",
  human_review_required: true,
  serving_claim: false,
  limitations: [
    "NOT_PHYSICAL_CAPACITY_VALIDATED",
    "THRESHOLD_COMPARATOR_ASSUMPTION",
    "PHYSICAL_FEASIBILITY_UNKNOWN",
  ],
  publication_identity_sha256: reviewSnapshot.publication_identity_sha256,
  source_provenance: provenance,
};
export const exampleSummary: AlternativeSetSummaryResponse = {
  set_id: exampleSet.set_id,
  canonical_unit_id: exampleSet.canonical_unit_id,
  origin: ORIGIN,
  target: "registrations",
  donor: exampleSet.donor,
  budget: 1,
  abstained: false,
  abstention_codes: [],
  receiver_candidates_considered: 184,
  receiver_candidates_eligible: 6,
  donor_minimum_transfer_fraction: 0.30291609871171393,
  alternative_count: 1,
  publication_identity_sha256: reviewSnapshot.publication_identity_sha256,
};
const abstainedSet = (budget: number): AlternativeSetResponse => ({
  ...exampleSet,
  set_id: `858cc17286c82b2fcfff03a5d6e93223106d0359b5912e7bbd296055fd60e457-${budget.toFixed(2)}`,
  canonical_unit_id:
    "858cc17286c82b2fcfff03a5d6e93223106d0359b5912e7bbd296055fd60e457",
  donor: {
    signal_id: DEMO_SIGNAL_ID,
    org_code: "000V",
    profile_code: "391",
    region_code: "39",
    series_id: "hp:000V:391",
    displayed_severity: "HIGH",
    priority_support_class: "direct_supported",
    materiality_status: "materiality_rule_not_triggered",
    binding_horizons: [1, 2, 3, 4, 7, 8, 9, 10, 11, 14],
    inbox_rank: 1,
  },
  budget,
  abstained: true,
  abstention_codes: ["RECEIVER_BLOCKED"],
  rejected_receiver_counts: {
    RECEIVER_BLOCKED: 4,
    RECEIVER_OUTSIDE_SAME_REGION_POLICY: 57,
  },
  receiver_candidates_considered: 61,
  receiver_candidates_eligible: 4,
  donor_minimum_transfer_fraction: 0.8859101796327441,
  alternatives: [],
});
export const demoAlternatives: SignalDecisionAlternativesResponse = {
  snapshot: reviewSnapshot,
  signal_id: DEMO_SIGNAL_ID,
  sets: [
    abstainedSet(0.05),
    abstainedSet(0.1),
    abstainedSet(0.25),
    abstainedSet(1),
  ],
};
export const demoCapabilities: ModelAssuranceCapabilityResponse[] = [
  {
    ...f.capability,
    capability_id: "flow_temporal_calibration",
    display_name: "Temporal count interval calibration",
    acceptance_verdict: "ACCEPT",
    evidence: {
      calibration_evidence: {
        hospital_registrations_final_coverage: 0.6992,
        hospital_registrations_validation_coverage: 0.8297,
      },
    },
  },
  {
    ...f.capability,
    capability_id: "flow_hierarchical_coherence",
    display_name: "Hierarchical central forecast coherence",
    acceptance_verdict: "ACCEPT",
  },
  {
    ...f.capability,
    capability_id: "forecast_stress_test",
    display_name: "Forecast Stress-Test Engine v1",
    product_consumption_status: "EVALUATION_ONLY",
  },
  {
    ...f.capability,
    capability_id: "decision_alternatives",
    display_name: "Constrained Decision Alternatives Engine v1",
    product_consumption_status: "EVALUATION_ONLY",
  },
  {
    ...f.capability,
    capability_id: "patient_journey_competing_risk_ml_challenger",
    display_name: "Patient Journey ML competing-risk challenger",
    evidence_status: "REJECTED",
    acceptance_verdict: "DO_NOT_PROMOTE",
    product_consumption_status: "NOT_FOR_PRODUCT",
  },
];
