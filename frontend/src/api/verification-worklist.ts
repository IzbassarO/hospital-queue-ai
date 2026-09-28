/**
 * Verification-worklist transport: runtime guards over the generated DTOs, then query hooks.
 *
 * The guard keeps the framing on the wire. `decision_owner` and `not_a_decision` are required on the publication
 * and on every row, so a response that lost them fails here with a clear error instead of reaching a screen that
 * would then present a review list as a decision. `yield_curve.disclosure` and `legacy_rule.role` are guarded the
 * same way: hindsight stays labelled, and the earlier binary rule stays a reference rather than the selector.
 */
import { useQuery } from "@tanstack/react-query";
import type {
  VerificationWorklistPublicationResponse,
  WorklistAreaResponse,
  WorklistHospitalResponse,
  WorklistItemResponse,
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

const base = "/verification-worklist";
const enc = encodeURIComponent;

/** One sentence in both interface languages; the UI picks by the current language, never by a fallback. */
const localisedSchema = object({ ru: str, kk: str });

const estimateTierSchema = literal(
  "hospital_profile",
  "region_profile",
  "profile",
  "global",
);

/** The source's own reasons a number rests on thin comparable history. */
export const historyReasonSchema = literal(
  "insufficient_comparable_history",
  "insufficient_and_degenerate_comparable_history",
  "degenerate_conditional_distribution",
);

/** Never optional: the four fields that keep a worklist a worklist. */
const framing = {
  publication_id: str,
  publication_identity_sha256: str,
  origin: isoDate,
  decision_owner: literal("SPECIALIST_DECIDES"),
  not_a_decision: localisedSchema,
};

export const worklistItemSchema: Schema<WorklistItemResponse> = object({
  ...framing,
  referral_id: num,
  rank: num,
  org_code: str,
  region_code: str,
  profile_code: str,
  profile_name: str,
  days_waited_at_origin: num,
  registration_date: nullable(isoDate),
  hospitalization_code: nullable(str),
  probability_admitted_30d: num,
  probability_admitted_horizon: num,
  horizon_days: num,
  estimate_tier: estimateTierSchema,
  verification_priority_score: num,
  comparable_training_at_risk_rows: num,
  history_quality_warning: bool,
  history_quality_reason_code: nullable(historyReasonSchema),
});

export const worklistAreaSchema: Schema<WorklistAreaResponse> = object({
  level: literal("region", "hospital"),
  code: str,
  name: str,
  region_code: nullable(str),
  formal_queue_count: num,
  history_quality_warning_count: num,
  history_quality_warning_share: num,
});

export const worklistHospitalSchema: Schema<WorklistHospitalResponse> = object({
  ...framing,
  org_code: str,
  org_name: str,
  region_code: str,
  region_name: str,
  formal_queue_count: num,
  history_quality_warning_count: num,
  history_quality_warning_share: num,
  region: worklistAreaSchema,
  items: array(worklistItemSchema),
  total: num,
  limit: num,
  offset: num,
});

export const worklistPublicationSchema: Schema<VerificationWorklistPublicationResponse> =
  object({
    publication_id: str,
    schema_version: str,
    contract_version: str,
    publication_identity_sha256: str,
    bundle_sha256: str,
    source_code_commit: str,
    origin: isoDate,
    published_at: isoDateTime,
    generated_at: nullable(isoDateTime),
    decision_owner: literal("SPECIALIST_DECIDES"),
    not_a_decision: localisedSchema,
    source_publication: object({
      publication_id: str,
      publication_identity_sha256: str,
      file_sha256: str,
      schema_version: num,
      model: str,
    }),
    ranking: object({
      definition: localisedSchema,
      keys: array(str),
      score_name: str,
      score_formula: str,
      wait_maturity_days: num,
      minimum_comparable_at_risk_rows: num,
      training_only_justification: str,
    }),
    legacy_rule: object({
      role: literal("AUDITED_REFERENCE_ONLY"),
      reason_code: str,
      minimum_days_waited: num,
      horizon_days: num,
      probability_strictly_below: num,
      selected_count: num,
      training_only_justification: str,
      statement: localisedSchema,
    }),
    history_quality: object({
      definition: localisedSchema,
      warning_count: num,
      warning_share: num,
      reason_counts: record(num),
    }),
    estimands: record(str),
    counts: object({ formal_queue_count: num, ranked_count: num }),
    yield_curve: object({
      disclosure: literal("HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"),
      definition: localisedSchema,
      outcome_source: str,
      outcome_source_identity_sha256: str,
      base: object({ evaluated: num, no_longer_current: num, share: num }),
      points: array(
        object({ checked: num, no_longer_current: num, share: num, lift: num }),
      ),
    }),
    limitations: array(str),
  });

export type WorklistItem = WorklistItemResponse;
export type WorklistArea = WorklistAreaResponse;
export type WorklistHospital = WorklistHospitalResponse;
export type WorklistPublication = VerificationWorklistPublicationResponse;
export type WorklistOrder = "rank" | "longest_wait";

export interface WorklistQuery {
  order?: WorklistOrder;
  historyWarning?: boolean | null;
  limit: number;
  offset: number;
}

export const verificationWorklistApi = {
  publication: async (): Promise<WorklistPublication> =>
    request(worklistPublicationSchema, `${base}/publication`),
  regions: async (): Promise<WorklistArea[]> =>
    request(array(worklistAreaSchema), `${base}/regions`),
  hospital: async (org: string, query: WorklistQuery) =>
    request(
      worklistHospitalSchema,
      buildPath(`${base}/hospitals/${enc(org)}`, {
        order: query.order ?? null,
        history_quality_warning:
          query.historyWarning == null ? null : String(query.historyWarning),
        limit: query.limit,
        offset: query.offset,
      }),
    ),
};

const STALE = 5 * 60 * 1000;

/** Null when nothing is published: the hospital screen then simply has no verification tab. */
export const useWorklistPublication = () =>
  useQuery({
    queryKey: ["verification-worklist", "publication"],
    queryFn: () => verificationWorklistApi.publication().catch(() => null),
    staleTime: STALE,
  });

export const useWorklistHospital = (
  org: string | null,
  query: WorklistQuery,
  enabled = true,
) =>
  useQuery({
    queryKey: ["verification-worklist", "hospital", org, query],
    queryFn: () => verificationWorklistApi.hospital(org as string, query),
    enabled: Boolean(org) && enabled,
    staleTime: STALE,
    placeholderData: (previous) => previous,
  });

export const useWorklistRegions = (enabled = true) =>
  useQuery({
    queryKey: ["verification-worklist", "regions"],
    queryFn: verificationWorklistApi.regions,
    enabled,
    staleTime: STALE,
  });
