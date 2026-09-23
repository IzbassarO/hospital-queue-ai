/** Review-evidence transport: generated DTO types → runtime guards → semantic hooks for the guided journey. */
import { useQuery } from "@tanstack/react-query";
import type {
  AlternativeSetResponse,
  AlternativeSetSummaryResponse,
  ReviewOverviewResponse,
  SignalDecisionAlternativesResponse,
  SignalStressTestResponse,
} from "../api/generated";
import { api, buildPath, request } from "../api/client";
import {
  array,
  bool,
  isoDate,
  isoDateTime,
  literal,
  nullable,
  num,
  object,
  record,
  str,
  unknownValue,
  type Schema,
} from "../api/schema";
import { pageSchema } from "../api/types";
import { severitySchema, supportSchema } from "../api/operational-schemas";

const strings = array(str);
const maybeNumber = nullable(num);
const maybeString = nullable(str);
const provenance = record(
  object({
    run_id: str,
    scientific_identity_sha256: str,
    artifact_sha256: {
      parse: (v: unknown, p?: string) =>
        typeof v === "string" ? str.parse(v, p) : strings.parse(v, p),
    } as Schema<string | string[]>,
    dataset_identity_sha256: maybeString,
    config_identity_sha256: maybeString,
    code_identity_sha256: maybeString,
  }),
);
const snapshot = object({
  publication_id: str,
  schema_version: str,
  contract_version: str,
  publication_identity_sha256: str,
  bundle_sha256: str,
  assurance_identity_sha256: str,
  operational_publication_identity_sha256: str,
  source_code_commit: str,
  current_origin: isoDate,
  freshness_state: literal("FRESH", "STALE", "DEGRADED", "UNKNOWN"),
  publication_status: literal("AVAILABLE", "EMPTY"),
  generated_at: nullable(isoDateTime),
  published_at: isoDateTime,
  scenario_count: num,
  scenario_entity_count: num,
  scenario_cell_count: num,
  alternative_set_count: num,
  alternative_count: num,
  source_provenance: provenance,
  limitations: strings,
});
const target = literal("registrations", "cohort_hospitalizations");
const falseOnly: Schema<false> = {
  parse: (v: unknown, p = "$") => {
    if (v !== false) throw new Error(`${p}: expected false`);
    return false as const;
  },
};
const trueOnly: Schema<true> = {
  parse: (v: unknown, p = "$") => {
    if (v !== true) throw new Error(`${p}: expected true`);
    return true as const;
  },
};
const scenarioStrict = object({
  scenario_id: str,
  scenario_type: literal("identity", "demand_multiplier"),
  classification: literal(
    "SAFE_NON_CAUSAL_STRESS_TEST",
    "MECHANISTIC_ACCOUNTING_SCENARIO",
  ),
  lever_type: str,
  multiplier: maybeNumber,
  scope_type: str,
  horizon_start: num,
  horizon_end: num,
  target,
  uncertainty_method: str,
  uncertainty_label: str,
  coverage_guarantee: falseOnly,
  causal_effect_claimed: falseOnly,
  serving_claim: falseOnly,
  baseline_reproduction: nullable(literal("PASS")),
  network_summary: object({
    daily_cells_total: num,
    severity_changed_count: num,
    severity_changed_share: num,
    severity_counts: record(num),
    entity_count: num,
    entity_severity_changed_count: num,
  }),
  evidence_facts: strings,
  limitations: strings,
});
const alternativesSummary = object({
  set_count: num,
  unit_count: num,
  sets_with_alternatives: num,
  alternative_count: num,
  receiver_worsening_count: num,
  verification_failure_count: num,
  full_verification_success_rate: num,
  transfer_budget_ladder: array(num),
  origins: array(isoDate),
  evaluation_population: str,
});
export const reviewOverviewSchema = object({
  snapshot,
  scenarios: array(scenarioStrict),
  alternatives_summary: alternativesSummary,
}) satisfies Schema<ReviewOverviewResponse>;

const cell = object({
  target_date: isoDate,
  horizon: num,
  baseline_central: num,
  baseline_lower: maybeNumber,
  baseline_upper: maybeNumber,
  baseline_severity: severitySchema,
  scenario_central: num,
  scenario_lower: maybeNumber,
  scenario_upper: maybeNumber,
  scenario_severity: severitySchema,
  threshold_value: maybeNumber,
  threshold_status: maybeString,
  scenario_uncertainty_status: literal(
    "TRANSFORMED_BASELINE_UNCERTAINTY_RANGE",
    "UNAVAILABLE",
    "NOT_SCENARIO_ADJUSTED",
  ),
  severity_changed: bool,
  source_reason_code: maybeString,
});
export const stressTestSchema = object({
  snapshot,
  signal_id: str,
  series_id: str,
  origin: isoDate,
  target,
  org_code: str,
  region_code: str,
  profile_code: str,
  outcomes: array(
    object({
      scenario: scenarioStrict,
      baseline_severity: severitySchema,
      scenario_severity: severitySchema,
      baseline_inbox_rank: maybeNumber,
      scenario_inbox_rank: maybeNumber,
      baseline_central: num,
      scenario_central: num,
      threshold_value: maybeNumber,
      absolute_delta: num,
      relative_delta: maybeNumber,
      severity_changed: bool,
      entered_primary_inbox: bool,
      left_primary_inbox: bool,
      first_crossing_date: nullable(isoDate),
      lead_time_days: maybeNumber,
      materiality_status: maybeString,
      scenario_headline: maybeString,
      scenario_reason: maybeString,
      scenario_range_available: bool,
      limitations: strings,
      cells: array(cell),
    }),
  ),
}) satisfies Schema<SignalStressTestResponse>;

const seriesRef = object({
  org_code: str,
  profile_code: str,
  region_code: str,
  series_id: str,
});
const stateCell = object({
  horizon: num,
  target_date: isoDate,
  central: num,
  lower: maybeNumber,
  upper: maybeNumber,
  severity: severitySchema,
  threshold_value: maybeNumber,
  threshold_status: maybeString,
});
const seriesState = object({
  displayed_severity: severitySchema,
  max_severity_7d: severitySchema,
  max_severity_14d: severitySchema,
  severity_evidence_horizon: maybeNumber,
  severity_evidence_date: nullable(isoDate),
  cells: array(stateCell),
});
const inboxOutcome = object({
  baseline_inbox_rank: maybeNumber,
  scenario_inbox_rank: maybeNumber,
  baseline_severity: severitySchema,
  scenario_severity: severitySchema,
  entered_primary_inbox: bool,
  left_primary_inbox: bool,
});
const alternative = object({
  alternative_id: str,
  donor: seriesRef,
  receiver: seriesRef,
  transfer_fraction: num,
  transfer_fraction_certification: str,
  transferred_total: num,
  transferred_by_horizon: array(
    object({ horizon: num, target_date: isoDate, moved: num }),
  ),
  donor_severity_before: severitySchema,
  donor_severity_after: severitySchema,
  receiver_severity_before: severitySchema,
  receiver_severity_after: severitySchema,
  donor_binding_horizons: array(num),
  donor_binding_cell: nullable(record(unknownValue)),
  receiver_binding_cell: nullable(record(unknownValue)),
  receiver_min_central_headroom: num,
  receiver_no_worse_constraint_satisfied: trueOnly,
  conservation_satisfied: trueOnly,
  budget_constraint_satisfied: trueOnly,
  source_central_goal_satisfied: trueOnly,
  verification_state: literal(
    "VERIFIED_FULL_ENGINE",
    "FAST_PATH_ONLY",
    "VERIFICATION_FAILED",
  ),
  forecast_support_tier: supportSchema,
  donor_support_class: supportSchema,
  receiver_support_class: supportSchema,
  receiver_range_evidence: literal("COMPLETE", "RANGE_LIMITED"),
  sensitivity_range_result: literal(
    "ROBUST_TO_TRANSFORMED_RANGE",
    "NOT_ROBUST_TO_TRANSFORMED_RANGE",
    "RANGE_EVIDENCE_INCOMPLETE",
  ),
  feasibility_status: literal("NOT_PHYSICAL_CAPACITY_VALIDATED"),
  capacity_checked: falseOnly,
  causal_effect_claimed: falseOnly,
  human_review_required: trueOnly,
  hierarchy_coherent: bool,
  donor_inbox: inboxOutcome,
  receiver_inbox: inboxOutcome,
  explanation_text: str,
  non_claims: strings,
  limitations: strings,
  baseline_donor_state: seriesState,
  scenario_donor_state: seriesState,
  baseline_receiver_state: seriesState,
  scenario_receiver_state: seriesState,
});
const donorRef = object({
  signal_id: str,
  org_code: str,
  profile_code: str,
  region_code: str,
  series_id: str,
  displayed_severity: severitySchema,
  priority_support_class: str,
  materiality_status: maybeString,
  binding_horizons: array(num),
  inbox_rank: maybeNumber,
});
export const alternativeSetSchema = object({
  set_id: str,
  canonical_unit_id: str,
  origin: isoDate,
  target,
  donor: donorRef,
  budget: num,
  abstained: bool,
  abstention_codes: strings,
  rejected_receiver_counts: record(num),
  receiver_candidates_considered: num,
  receiver_candidates_eligible: num,
  donor_minimum_transfer_fraction: maybeNumber,
  shortlist_bound: num,
  alternatives: array(alternative),
  verification_failure_count: num,
  scientific_output_sha256: str,
  execution_mode: literal("EVALUATION"),
  human_review_required: trueOnly,
  serving_claim: falseOnly,
  limitations: strings,
  publication_identity_sha256: str,
  source_provenance: provenance,
}) satisfies Schema<AlternativeSetResponse>;
export const alternativeSetSummarySchema = object({
  set_id: str,
  canonical_unit_id: str,
  origin: isoDate,
  target,
  donor: donorRef,
  budget: num,
  abstained: bool,
  abstention_codes: strings,
  receiver_candidates_considered: num,
  receiver_candidates_eligible: num,
  donor_minimum_transfer_fraction: maybeNumber,
  alternative_count: num,
  publication_identity_sha256: str,
}) satisfies Schema<AlternativeSetSummaryResponse>;
export const signalAlternativesSchema = object({
  snapshot,
  signal_id: str,
  sets: array(alternativeSetSchema),
}) satisfies Schema<SignalDecisionAlternativesResponse>;

export type ReviewOverview = ReviewOverviewResponse;
export type StressTest = SignalStressTestResponse;
export type StressOutcome = StressTest["outcomes"][number];
export type AlternativeSet = AlternativeSetResponse;
export type Alternative = AlternativeSet["alternatives"][number];
export type AlternativeSetSummary = AlternativeSetSummaryResponse;

const base = "/review-evidence";
const enc = encodeURIComponent;
export const reviewApi = {
  overview: () => request(reviewOverviewSchema, `${base}/overview`),
  stressTest: (signalId: string) =>
    request(stressTestSchema, `${base}/signals/${enc(signalId)}/stress-test`),
  signalAlternatives: (signalId: string) =>
    request(
      signalAlternativesSchema,
      `${base}/signals/${enc(signalId)}/decision-alternatives`,
    ),
  alternativeSets: (query: {
    origin?: string;
    region?: string;
    with_alternatives?: boolean;
    limit: number;
    offset: number;
  }) =>
    request(
      pageSchema(alternativeSetSummarySchema),
      buildPath(`${base}/decision-alternatives`, {
        ...query,
        with_alternatives:
          query.with_alternatives === undefined
            ? undefined
            : String(query.with_alternatives),
      }),
    ),
  alternativeSet: (setId: string) =>
    request(
      alternativeSetSchema,
      `${base}/decision-alternatives/${enc(setId)}`,
    ),
};
const settings = { staleTime: 60_000, retry: false } as const;
export const useReviewOverview = () =>
  useQuery({
    queryKey: ["review", "overview"],
    queryFn: reviewApi.overview,
    ...settings,
  });
export const useStressTest = (signalId: string) =>
  useQuery({
    queryKey: ["review", "stress-test", signalId],
    queryFn: () => reviewApi.stressTest(signalId),
    enabled: signalId !== "",
    ...settings,
  });
export const useSignalAlternatives = (signalId: string) =>
  useQuery({
    queryKey: ["review", "signal-alternatives", signalId],
    queryFn: () => reviewApi.signalAlternatives(signalId),
    enabled: signalId !== "",
    ...settings,
  });
export const useAlternativeSets = (query: {
  origin?: string;
  region?: string;
  with_alternatives?: boolean;
  limit: number;
  offset: number;
}) =>
  useQuery({
    queryKey: ["review", "alternative-sets", query],
    queryFn: () => reviewApi.alternativeSets(query),
    enabled: Boolean(query.origin),
    ...settings,
  });
export const useAlternativeSet = (setId: string) =>
  useQuery({
    queryKey: ["review", "alternative-set", setId],
    queryFn: () => reviewApi.alternativeSet(setId),
    enabled: setId !== "",
    ...settings,
  });

/**
 * Observed daily registrations before the origin, from the operational data mart (same source table as the
 * accepted flow evidence). Context only: it is not part of the frozen publication and never used for scoring.
 */
export const useObservedHistory = (
  org: string | null,
  profile: string | null,
  origin: string,
) =>
  useQuery({
    queryKey: ["demo", "observed", org, profile, origin],
    queryFn: async () => {
      const card = await api.hospitalCard(org ?? "", profile ?? "");
      return card.series
        .filter((p) => p.date <= origin)
        .map((p) => ({ date: p.date, registrations: p.registrations }));
    },
    enabled: Boolean(org && profile),
    staleTime: Infinity,
    retry: false,
  });
