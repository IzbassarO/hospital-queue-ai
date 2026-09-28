/**
 * Per-referral estimate transport: runtime guards over the generated DTOs, then query hooks.
 *
 * Two publications arrive on one row and the guard keeps them apart. `observed_after_origin` is hindsight the
 * waiting list measured; `estimate` is what the model could say on the origin day, and it is `null` — never a
 * zero, never an empty string — when the publication does not cover that referral.
 */
import { useQuery } from "@tanstack/react-query";
import type {
  QueueReferralResponse,
  ReferralEstimateResponse,
  ReferralEstimatesPublicationResponse,
} from "./generated";
import { buildPath, request } from "./client";
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
  type Schema,
} from "./schema";
import { pageSchema } from "./types";
import { waitingReferralShape } from "./waiting-list";

const base = "/referral-estimates";
const enc = encodeURIComponent;

const journeyModelSchema = literal(
  "aalen_johansen",
  "xgboost_aft",
  "discrete_competing_risk",
);
const estimateTierSchema = literal(
  "hospital_profile",
  "region_profile",
  "profile",
  "national",
);
const abstentionSchema = literal("NO_ADMISSION_IN_COMPARABLE_HISTORY");

export const referralEstimateSchema: Schema<ReferralEstimateResponse> = object({
  publication_id: str,
  publication_identity_sha256: str,
  origin: isoDate,
  selected_model: journeyModelSchema,
  estimate_tier: estimateTierSchema,
  similar_training_rows: num,
  admitted_7d: num,
  admitted_14d: num,
  admitted_30d: num,
  refused_30d: num,
  still_waiting_30d: num,
  window_lower_days: nullable(num),
  window_upper_days: nullable(num),
  window_coverage: num,
  abstention_reason: nullable(abstentionSchema),
  refusal_attention: bool,
  degenerate_30d: bool,
});

export const queueReferralSchema: Schema<QueueReferralResponse> = object({
  ...waitingReferralShape,
  estimate: nullable(referralEstimateSchema),
});

const candidateSchema = object({
  model_key: journeyModelSchema,
  role: literal("baseline", "candidate"),
  accepted: nullable(bool),
  overall_mean_brier: num,
  overall_delta: nullable(num),
  worst_bucket_delta: nullable(num),
  strict_overall_improvement: nullable(bool),
  within_bucket_tolerance: nullable(bool),
  brier_by_horizon: record(num),
});

const reliabilityBinSchema = object({
  horizon_days: num,
  outcome: literal("hospitalized", "refused"),
  bin_index: num,
  n: num,
  mean_predicted: num,
  observed_rate: num,
  probability_min: num,
  probability_max: num,
});

export const referralEstimatesPublicationSchema: Schema<ReferralEstimatesPublicationResponse> =
  object({
    publication_id: str,
    schema_version: str,
    contract_version: str,
    publication_identity_sha256: str,
    bundle_sha256: str,
    source_code_commit: str,
    origin: isoDate,
    outcome_cutoff: isoDateTime,
    published_at: isoDateTime,
    generated_at: nullable(isoDateTime),
    referral_count: num,
    horizons: array(num),
    admission_window_coverage: num,
    source_run: object({
      run_id: str,
      artifact_identity_sha256: str,
      scientific_identity_sha256: str,
      training_sha256: str,
      scoring_sha256: str,
      seed: num,
      library_versions: record(str),
    }),
    selection: object({
      metric: str,
      decision_rule: str,
      tolerance: num,
      require_strict_overall_improvement: bool,
      selected_model: journeyModelSchema,
      fallback_used: bool,
      candidates: array(candidateSchema),
    }),
    calibration: object({
      disclosure: literal("HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"),
      model_key: journeyModelSchema,
      rows: num,
      bins: array(reliabilityBinSchema),
    }),
    estimate_tiers: record(num),
    abstention_counts: record(num),
    degeneracy: object({
      definition: str,
      count: num,
      by_outcome: record(num),
    }),
    attention: object({
      metric: literal("refused_30d"),
      quantile: num,
      threshold: num,
      definition: str,
      intended_use: str,
      flagged_count: num,
    }),
    limitations: array(str),
    matches_waiting_list: bool,
  });

export type ReferralEstimate = ReferralEstimateResponse;
export type QueueReferral = QueueReferralResponse;
export type ReferralEstimatesPublication = ReferralEstimatesPublicationResponse;
export type EstimateTier = ReferralEstimateResponse["estimate_tier"];
export type QueueOrder =
  "longest_wait" | "shortest_wait" | "highest_refusal_risk";

export interface QueueQuery {
  profile?: string | null;
  order?: QueueOrder;
  attention?: boolean;
  limit: number;
  offset: number;
}

export const referralEstimatesApi = {
  publication: async (): Promise<ReferralEstimatesPublication> =>
    request(referralEstimatesPublicationSchema, `${base}/publication`),
  queue: async (org: string, query: QueueQuery) =>
    request(
      pageSchema(queueReferralSchema),
      buildPath(`${base}/hospitals/${enc(org)}/referrals`, {
        profile: query.profile ?? null,
        order: query.order ?? null,
        attention: query.attention ? "true" : null,
        limit: query.limit,
        offset: query.offset,
      }),
    ),
};

const STALE = 5 * 60 * 1000;

/**
 * The active estimate publication, or null when none is published. A missing publication is a normal state of the
 * product — the queue still answers — so it resolves to null instead of throwing and blanking the screen.
 */
export const useReferralEstimatesPublication = () =>
  useQuery({
    queryKey: ["referral-estimates", "publication"],
    queryFn: () => referralEstimatesApi.publication().catch(() => null),
    staleTime: STALE,
  });

export const useQueueReferrals = (org: string | null, query: QueueQuery) =>
  useQuery({
    queryKey: ["referral-estimates", "queue", org, query],
    queryFn: () => referralEstimatesApi.queue(org as string, query),
    enabled: Boolean(org),
    staleTime: STALE,
    placeholderData: (previous) => previous,
  });
