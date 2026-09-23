/** Runtime guards over generated DTOs. Generated files remain generator-owned. */
import type {
  OperationalSignalResponse,
  OperationalForecastResponse,
  OperationalOverviewResponse,
  OperationalRegionResponse,
  OperationalHospitalProfileResponse,
  ModelAssuranceCapabilityResponse,
  ModelAssuranceSnapshotResponse,
  SignalExplanationResponse,
} from "./generated";
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
} from "./schema";
import { pageSchema } from "./types";

/** Only apply explicit OpenAPI/Pydantic defaults to omitted properties.
 * Supplied nulls, numbers, strings and enums still pass unchanged through the guard.
 * This does not derive missing scientific values.
 */
function withDefaults<T extends object>(
  schema: Schema<T>,
  defaults: Partial<T>,
): Schema<T> {
  return {
    parse(value, path) {
      return schema.parse(
        typeof value === "object" && value !== null && !Array.isArray(value)
          ? { ...defaults, ...value }
          : value,
        path,
      );
    },
  };
}

const strings = array(str);
const maybeNumber = nullable(num);
const maybeString = nullable(str);
export const severitySchema = literal(
  "HIGH",
  "ELEVATED",
  "WATCH",
  "NORMAL",
  "UNSUPPORTED",
);
export const supportSchema = literal(
  "DIRECT_SUPPORTED",
  "FALLBACK_LIMITED",
  "UNSUPPORTED",
);
const fallback = literal(
  "NOT_APPLICABLE",
  "REGION_PROFILE_FALLBACK",
  "OTHER_FALLBACK",
  "UNSUPPORTED",
);
const uncertainty = literal(
  "CALIBRATED",
  "INSUFFICIENT_CALIBRATION_SUPPORT",
  "UNAVAILABLE",
);
const freshness = literal("FRESH", "STALE", "DEGRADED", "UNKNOWN");
const target = literal("registrations", "cohort_hospitalizations");
const signalType = literal("preventive_flow_pressure", "observed_unusual_flow");
const scalarOrStrings: Schema<string | string[]> = {
  parse: (v, p) =>
    typeof v === "string" ? str.parse(v, p) : strings.parse(v, p),
};
const evidenceValue: Schema<string | number | boolean | null> = {
  parse: (v, p) =>
    v === null
      ? null
      : typeof v === "number"
        ? num.parse(v, p)
        : typeof v === "boolean"
          ? bool.parse(v, p)
          : str.parse(v, p),
};
const provenance = record(
  withDefaults(
    object({
      run_id: str,
      scientific_identity_sha256: str,
      artifact_sha256: scalarOrStrings,
      dataset_identity_sha256: maybeString,
      config_identity_sha256: maybeString,
      code_identity_sha256: maybeString,
    }),
    {
      dataset_identity_sha256: null,
      config_identity_sha256: null,
      code_identity_sha256: null,
    },
  ),
);
const snapshot = object({
  publication_id: str,
  schema_version: str,
  contract_version: str,
  publication_identity_sha256: str,
  bundle_sha256: str,
  assurance_identity_sha256: str,
  source_code_commit: str,
  current_origin: isoDate,
  freshness_state: freshness,
  publication_status: literal("AVAILABLE", "DEGRADED", "EMPTY"),
  generated_at: nullable(isoDateTime),
  published_at: isoDateTime,
  forecast_count: num,
  signal_count: num,
  source_provenance: provenance,
  limitations: strings,
});
const counts = withDefaults(
  object({
    total_signals: num,
    high: num,
    elevated: num,
    watch: num,
    normal: num,
    unsupported_severity: num,
    preventive_pressure: num,
    observed_unusual_flow: num,
    direct_supported: num,
    fallback_limited: num,
    unsupported_support: num,
    calibrated: num,
    uncertainty_limited_or_unavailable: num,
  }),
  {
    total_signals: 0,
    high: 0,
    elevated: 0,
    watch: 0,
    normal: 0,
    unsupported_severity: 0,
    preventive_pressure: 0,
    observed_unusual_flow: 0,
    direct_supported: 0,
    fallback_limited: 0,
    unsupported_support: 0,
    calibrated: 0,
    uncertainty_limited_or_unavailable: 0,
  },
);
const rawQuantiles = nullable(
  object({
    p10: num,
    p50: num,
    p90: num,
    semantics: literal("UNCHANGED_MODEL_EVIDENCE"),
  }),
);
export const signalSchema = withDefaults(
  object({
    signal_id: str,
    signal_type: signalType,
    series_id: str,
    origin: isoDate,
    target,
    org_code: maybeString,
    region_code: maybeString,
    profile_code: maybeString,
    inbox_rank: maybeNumber,
    severity: severitySchema,
    headline: str,
    concise_reason: str,
    materiality_status: maybeString,
    support_status: supportSchema,
    fallback_status: fallback,
    uncertainty_status: uncertainty,
    pressure_basis: nullable(literal("historical_flow_proxy_v1")),
    threshold_value: maybeNumber,
    threshold_status: maybeString,
    forecast_value: maybeNumber,
    uncertainty_lower: maybeNumber,
    uncertainty_upper: maybeNumber,
    first_crossing_date: nullable(isoDate),
    lead_time_days: maybeNumber,
    observed_anomaly_status: maybeString,
    observed_anomaly_present: bool,
    data_freshness: nullable(isoDate),
    reason_codes: strings,
    evidence_facts: strings,
    provenance_keys: strings,
    anomaly_evidence: nullable(
      object({
        observed_value: num,
        weekly_residual: num,
        reference_median_residual: num,
        reference_mad: num,
        robust_z: maybeNumber,
        reference_sample_count: num,
        reference_max_date: isoDate,
        causal_claim: {
          parse: (v: unknown) => {
            if (v !== false) throw new Error("causal claim must be false");
            return false as const;
          },
        },
      }),
    ),
    limitations: strings,
    publication_identity_sha256: str,
    source_provenance: provenance,
  }),
  {
    org_code: null,
    region_code: null,
    profile_code: null,
    inbox_rank: null,
    materiality_status: null,
    pressure_basis: null,
    threshold_value: null,
    threshold_status: null,
    forecast_value: null,
    uncertainty_lower: null,
    uncertainty_upper: null,
    first_crossing_date: null,
    lead_time_days: null,
    observed_anomaly_status: null,
    observed_anomaly_present: false,
    data_freshness: null,
    evidence_facts: [],
    anomaly_evidence: null,
    limitations: [],
  },
) satisfies Schema<OperationalSignalResponse>;
export const forecastSchema = withDefaults(
  object({
    series_id: str,
    level: literal("hospital", "region", "national"),
    origin: isoDate,
    target_date: isoDate,
    horizon: num,
    target,
    org_code: maybeString,
    region_code: maybeString,
    profile_code: maybeString,
    central_value: num,
    central_semantics: literal("P50", "POINT_FORECAST", "BOTTOM_UP_CENTRAL"),
    raw_quantiles: rawQuantiles,
    calibrated_uncertainty: nullable(
      object({
        lower: num,
        upper: num,
        nominal_coverage: num,
        calibration_status: literal("CALIBRATED"),
        support_class: str,
        calibration_version: str,
      }),
    ),
    calibration_status: literal(
      "CALIBRATED",
      "INSUFFICIENT_SUPPORT",
      "NOT_APPLICABLE",
    ),
    prediction_source: literal(
      "DIRECT",
      "REGION_PROFILE_FALLBACK",
      "BOTTOM_UP_AGGREGATE",
      "UNSUPPORTED",
    ),
    hierarchy_status: str,
    support_status: supportSchema,
    fallback_status: fallback,
    uncertainty_status: uncertainty,
    provenance_keys: strings,
    evidence_facts: strings,
    limitations: strings,
    publication_identity_sha256: str,
    source_provenance: provenance,
  }),
  {
    org_code: null,
    region_code: null,
    profile_code: null,
    raw_quantiles: null,
    calibrated_uncertainty: null,
    evidence_facts: [],
    limitations: [],
  },
) satisfies Schema<OperationalForecastResponse>;
export const operationalOverviewSchema = object({
  snapshot,
  national: counts,
  regions: array(object({ region_code: str, counts })),
}) satisfies Schema<OperationalOverviewResponse>;
export const operationalRegionSchema = object({
  snapshot,
  region_code: str,
  counts,
  top_signals: array(signalSchema),
  forecast_point_count: num,
  available_origins: array(isoDate),
  available_targets: array(target),
}) satisfies Schema<OperationalRegionResponse>;
export const operationalHospitalSchema = object({
  snapshot,
  org_code: str,
  region_code: maybeString,
  profile_code: str,
  counts,
  signals: array(signalSchema),
  forecast_point_count: num,
  available_origins: array(isoDate),
  available_targets: array(target),
}) satisfies Schema<OperationalHospitalProfileResponse>;
export const signalPageSchema = pageSchema(signalSchema);
export const forecastPageSchema = pageSchema(forecastSchema);
const evidenceStatus = literal("ACCEPTED", "REJECTED", "EXPERIMENTAL");
const acceptance = literal(
  "ACCEPT",
  "ACCEPT_WITH_P2",
  "DO_NOT_PROMOTE",
  "NOT_APPLICABLE",
);
const consumption = literal(
  "ELIGIBLE_AFTER_INGESTION",
  "EVALUATION_ONLY",
  "REFERENCE_ONLY",
  "NOT_FOR_PRODUCT",
);
const identity = object({
  status: literal("AVAILABLE", "UNKNOWN", "NOT_APPLICABLE"),
  value: nullable(scalarOrStrings),
  reason: str,
});
export const capabilitySchema = object({
  capability_id: str,
  display_name: str,
  evidence_status: evidenceStatus,
  acceptance_verdict: acceptance,
  product_consumption_status: consumption,
  identities: object({
    run_id: identity,
    scientific_identity_sha256: identity,
    artifact_sha256: identity,
    dataset_identity_sha256: identity,
    config_identity_sha256: identity,
    code_identity_sha256: identity,
    model_identity: identity,
    estimand_id: identity,
    calibration_identity: identity,
    hierarchy_identity: identity,
    pressure_provider_identity: identity,
    prioritization_identity: identity,
    scenario_identity: identity,
    decision_alternative_identity: identity,
  }),
  support: object({
    support_semantics: array(supportSchema),
    range_semantics: array(literal("COMPLETE", "RANGE_LIMITED")),
  }),
  governance: object({
    human_review_required: bool,
    autonomous_action: bool,
    capacity_checked: bool,
    causal_effect_claimed: bool,
    serving_claim: bool,
    physical_feasibility_status: literal(
      "VALIDATED",
      "NOT_VALIDATED",
      "UNKNOWN",
      "NOT_APPLICABLE",
    ),
    promotion_status: literal(
      "PROMOTED",
      "HUMAN_REVIEW_ONLY",
      "NO_PROMOTION",
      "NOT_APPLICABLE",
    ),
  }),
  freshness: object({ state: freshness, reason: str }),
  evidence: record(unknownValue),
  limitations: strings,
  allowed_claims: strings,
  forbidden_claims: strings,
}) satisfies Schema<ModelAssuranceCapabilityResponse>;
export const assuranceSnapshotSchema = object({
  assurance_id: str,
  contract_version: str,
  schema_version: str,
  assurance_identity_sha256: str,
  bundle_sha256: str,
  source_code_commit: str,
  ml_freeze_status: str,
  product_contract_version: str,
  generated_at: nullable(isoDateTime),
  published_at: isoDateTime,
  is_active: bool,
  capability_count: num,
  failed_evidence_history: array(record(unknownValue)),
  claim_boundaries: record(unknownValue),
  monitoring_expectations: array(record(unknownValue)),
  freshness_policy: record(unknownValue),
}) satisfies Schema<ModelAssuranceSnapshotResponse>;
export const explanationSchema = object({
  subject: object({
    signal_id: str,
    signal_type: signalType,
    series_id: str,
    target,
    origin: isoDate,
    org_code: maybeString,
    region_code: maybeString,
    profile_code: maybeString,
    severity: severitySchema,
    inbox_rank: maybeNumber,
  }),
  summary: str,
  why_flagged: strings,
  key_evidence: array(
    withDefaults(object({ code: str, statement: str, value: evidenceValue }), {
      value: null,
    }),
  ),
  uncertainty: object({
    status: uncertainty,
    narrative: str,
    central_value: maybeNumber,
    central_semantics: maybeString,
    target_date: nullable(isoDate),
    horizon_days: maybeNumber,
    raw_quantiles: rawQuantiles,
    calibrated_lower: maybeNumber,
    calibrated_upper: maybeNumber,
    nominal_coverage: maybeNumber,
    calibration_status: maybeString,
  }),
  support: object({
    status: supportSchema,
    fallback_status: fallback,
    prediction_source: maybeString,
    narrative: str,
  }),
  limitations: strings,
  suggested_review_questions: strings,
  provenance: object({
    publication_id: str,
    publication_identity_sha256: str,
    assurance_identity_sha256: str,
    source_provenance: provenance,
    model_assurance_capabilities: array(
      object({
        capability_id: str,
        evidence_status: str,
        acceptance_verdict: str,
        product_consumption_status: str,
        human_review_required: bool,
        autonomous_action: bool,
        capacity_checked: bool,
        causal_effect_claimed: bool,
      }),
    ),
  }),
  generation_mode: literal(
    "DETERMINISTIC",
    "NARRATED",
    "DETERMINISTIC_FALLBACK",
  ),
}) satisfies Schema<SignalExplanationResponse>;
