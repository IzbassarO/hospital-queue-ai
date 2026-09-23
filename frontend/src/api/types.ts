/**
 * Response schemas of /api/v1 — mirror backend/app/schemas/*.py and docs/api.md §6.
 * Types are inferred from the schemas so the two cannot drift apart.
 */
import {
  array,
  bool,
  extend,
  type Infer,
  isoDate,
  isoDateTime,
  literal,
  nullable,
  num,
  object,
  record,
  type Schema,
  str,
  unknownValue,
} from "./schema";

export const statusSchema = literal(
  "high",
  "elevated",
  "normal",
  "insufficient_data",
);
export type Status = Infer<typeof statusSchema>;

export function pageSchema<T>(item: Schema<T>) {
  return object({ items: array(item), total: num, limit: num, offset: num });
}
export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

export const healthSchema = object({
  status: str,
  database: str,
  marts_as_of_date: nullable(isoDate),
  marts_built_at: nullable(isoDateTime),
});
export type Health = Infer<typeof healthSchema>;

export const areaKpisSchema = object({
  code: str,
  name: str,
  level: str,
  queue_now: num,
  registrations_28d: num,
  hospitalizations_28d: num,
  refusals_28d: num,
  refusal_rate_28d: nullable(num),
  median_wait_28d: nullable(num),
  n_waits_28d: num,
  forecast_registrations_14d: nullable(num),
  forecast_hospitalizations_14d: nullable(num),
  high_risk_share: nullable(num),
  n_hospitals: num,
  n_hospital_profiles: num,
  n_hospital_profiles_ranked: num,
  load_index_max: nullable(num),
  n_hospitals_high_load: num,
  n_hospital_profiles_high_load: num,
  high_load_share: nullable(num),
});
export type AreaKpis = Infer<typeof areaKpisSchema>;

export const overviewSchema = object({
  as_of_date: isoDate,
  built_at: isoDateTime,
  thresholds: object({
    load_index_high: num,
    load_index_elevated: num,
    min_registrations_28d: num,
    queue_trend_national_median_4w: nullable(num),
  }),
  national: areaKpisSchema,
  regions: array(areaKpisSchema),
});
export type Overview = Infer<typeof overviewSchema>;

export const componentsSchema = object({
  backlog_score: nullable(num),
  refusal_score: nullable(num),
  trend_score: nullable(num),
});
export type LoadIndexComponents = Infer<typeof componentsSchema>;

const statusMetricsSchema = object({
  as_of_date: isoDate,
  queue_now: num,
  registrations_28d: num,
  hospitalizations_28d: num,
  refusals_28d: num,
  refusal_rate_28d: nullable(num),
  n_waits_28d: num,
  median_wait_28d: nullable(num),
  daily_throughput_28d: num,
  backlog_days: nullable(num),
  forecast_registrations_14d: nullable(num),
  forecast_hospitalizations_14d: nullable(num),
  n_test_referrals: num,
  high_risk_share: nullable(num),
  queue_trend_raw_4w: nullable(num),
  queue_trend_4w: nullable(num),
  has_sufficient_data: bool,
  load_index: nullable(num),
  status: statusSchema,
  status_label: str,
  components: componentsSchema,
});

export const regionProfileStatusSchema = extend(statusMetricsSchema, {
  region_code: str,
  region_name: str,
  profile_code: str,
  profile_name: str,
  n_hospitals: num,
  n_hospitals_high_load: num,
  load_index_max_hospital: nullable(num),
});
export type RegionProfileStatus = Infer<typeof regionProfileStatusSchema>;

export const regionDetailSchema = object({
  region: areaKpisSchema,
  profiles: array(regionProfileStatusSchema),
});
export type RegionDetail = Infer<typeof regionDetailSchema>;

export const hospitalProfileStatusSchema = extend(statusMetricsSchema, {
  region_code: str,
  region_name: str,
  org_code: str,
  org_name: str,
  profile_code: str,
  profile_name: str,
  forecast_method: nullable(str),
  region_rank: nullable(num),
  region_n_ranked: num,
  in_region_top: bool,
});
export type HospitalProfileStatus = Infer<typeof hospitalProfileStatusSchema>;
export const hospitalPageSchema = pageSchema(hospitalProfileStatusSchema);

export const explanationFactorSchema = object({
  feature: str,
  label: str,
  short_label: str,
  mean_abs_effect: num,
  mean_effect: num,
  unit: str,
  direction: str,
  share_in_top5: num,
  most_common_value: nullable(str),
  most_common_value_display: str,
});
export type ExplanationFactor = Infer<typeof explanationFactorSchema>;

export const hospitalCardSchema = object({
  status: hospitalProfileStatusSchema,
  series: array(
    object({
      date: isoDate,
      registrations: num,
      hospitalizations: num,
      refusals: num,
      queue: num,
    }),
  ),
  forecast: object({
    origin_date: nullable(isoDate),
    model_version: nullable(str),
    method: nullable(str),
    points: array(
      object({
        date: isoDate,
        horizon: num,
        registrations: num,
        hospitalizations: num,
      }),
    ),
    note: str,
  }),
  explanation_factors: object({
    n_referrals: num,
    wait_time: array(explanationFactorSchema),
    refusal_risk: array(explanationFactorSchema),
  }),
});
export type HospitalCard = Infer<typeof hospitalCardSchema>;
export type DailyPoint = HospitalCard["series"][number];
export type ForecastPoint = HospitalCard["forecast"]["points"][number];

/** One top-5 factor of a single referral (pred_referral.explanation) */
export const referralFactorSchema = object({
  feature: str,
  value: nullable(unknownValue),
  value_display: str,
  short_label: str,
  effect: num,
  effect_in_unit: num,
  unit: str,
  direction: str,
  text: str,
});
export type ReferralFactor = Infer<typeof referralFactorSchema>;

export const referralSchema = object({
  hospitalization_code: str,
  registration_date: isoDate,
  icd10_code: nullable(str),
  diagnosis_name: nullable(str),
  referral_purpose: nullable(str),
  pred_wait_days: num,
  pred_refusal_prob: num,
  is_high_risk: bool,
  explanation: record(array(referralFactorSchema)),
});
export type Referral = Infer<typeof referralSchema>;
export const referralPageSchema = pageSchema(referralSchema);

export const alternativeSchema = object({
  recommendation_id: str,
  org_code: str,
  org_name: str,
  region_code: str,
  profile_code: str,
  expected_wait_current: num,
  expected_wait_alternative: num,
  delta_days: num,
  refusal_rate_current: nullable(num),
  refusal_rate_alternative: nullable(num),
  backlog_days_current: num,
  backlog_days_alternative: num,
  load_index_alternative: nullable(num),
  registrations_28d_alternative: num,
  method: str,
  explanation: str,
});
export type Alternative = Infer<typeof alternativeSchema>;

export const recommendationsSchema = object({
  as_of_date: isoDate,
  region_code: str,
  region_name: str,
  org_code: str,
  org_name: str,
  profile_code: str,
  profile_name: str,
  method: str,
  eligible: bool,
  reason: nullable(str),
  current: object({
    load_index: nullable(num),
    status: statusSchema,
    region_rank: nullable(num),
    region_n_ranked: num,
    in_region_top: bool,
    backlog_days: nullable(num),
    median_wait_28d: nullable(num),
    refusal_rate_28d: nullable(num),
    registrations_28d: num,
  }),
  rule: object({
    region_top_fraction: num,
    min_wait_delta_days: num,
    max_alternatives: num,
    min_registrations_28d: num,
  }),
  alternatives: array(alternativeSchema),
  disclaimer: str,
});
export type Recommendations = Infer<typeof recommendationsSchema>;

export const decisionActionSchema = literal("confirm", "reject", "defer");
export type DecisionAction = Infer<typeof decisionActionSchema>;

export const decisionSchema = object({
  id: num,
  created_at: isoDateTime,
  region_code: str,
  org_code: str,
  profile_code: str,
  recommendation_id: nullable(str),
  alternative_org_code: nullable(str),
  alternative_org_name: nullable(str),
  action: decisionActionSchema,
  comment: nullable(str),
  actor: str,
  idempotency_key: nullable(str),
  api_key_label: nullable(str),
});
export type Decision = Infer<typeof decisionSchema>;
export const decisionPageSchema = pageSchema(decisionSchema);

export interface DecisionCreate {
  region_code: string;
  org_code: string;
  profile_code: string;
  recommendation_id: string | null;
  alternative_org_code: string | null;
  action: DecisionAction;
  comment: string | null;
  actor: string;
  /** client-generated per submission: a retry returns the stored decision instead of a duplicate */
  idempotency_key: string;
}

export const alertSchema = object({
  region_code: str,
  region_name: str,
  org_code: str,
  org_name: str,
  profile_code: str,
  profile_name: str,
  load_index: nullable(num),
  status: statusSchema,
  status_label: str,
  region_rank: nullable(num),
  region_n_ranked: num,
  queue_now: num,
  backlog_days: nullable(num),
  queue_trend_raw_4w: nullable(num),
  queue_trend_4w: nullable(num),
  refusal_rate_28d: nullable(num),
  reasons: array(str),
});
export type Alert = Infer<typeof alertSchema>;
export const alertPageSchema = pageSchema(alertSchema);

const metricRowSchema = record(unknownValue);
export type MetricRow = Record<string, unknown>;

export const modelInfoSchema = object({
  model_name: str,
  title: str,
  intended_use: nullable(str),
  limitations: array(str),
  display_names: record(str),
  version: str,
  trained_at: isoDateTime,
  train_window: record(unknownValue),
  population: nullable(record(unknownValue)),
  headline: array(metricRowSchema),
  baselines: array(metricRowSchema),
  beats_baselines: nullable(bool),
});
export type ModelInfo = Infer<typeof modelInfoSchema>;
export const modelsSchema = array(modelInfoSchema);

const organizationsSchema = array(
  object({ code: str, name: str, region_code: nullable(str) }),
);
/** `organizations` is a later addition of the contract: absent in older responses/fixtures → []. */
const optionalOrganizations: Schema<Infer<typeof organizationsSchema>> = {
  parse: (value, path) =>
    value === undefined ? [] : organizationsSchema.parse(value, path),
};
export const dictionariesSchema = {
  ...object({
    national_code: str,
    regions: array(object({ code: str, name: str })),
    profiles: array(object({ code: str, name: str, is_day_hospital: bool })),
  }),
  parse(value: unknown, path?: string) {
    const base = object({
      national_code: str,
      regions: array(object({ code: str, name: str })),
      profiles: array(object({ code: str, name: str, is_day_hospital: bool })),
    }).parse(value, path);
    const organizations = optionalOrganizations.parse(
      (value as { organizations?: unknown }).organizations,
      `${path ?? "$"}.organizations`,
    );
    return { ...base, organizations };
  },
};
export type Dictionaries = Infer<typeof dictionariesSchema>;

export const configSchema = object({
  as_of_date: isoDate,
  built_at: isoDateTime,
  window_days: num,
  window_start: isoDate,
  trend_start: isoDate,
  trend_end: isoDate,
  test_start: isoDate,
  test_end: isoDate,
  series_start: isoDate,
  forecast_horizon: num,
  min_registrations_28d: num,
  backlog_min_daily_throughput: num,
  high_risk_threshold: num,
  queue_trend_national_median_4w: nullable(num),
  load_index: object({
    weights: object({ backlog_rank: num, refusal_rate: num, queue_trend: num }),
    refusal_rate_cap: num,
    queue_trend_cap_pct: num,
  }),
  status_thresholds: object({ high: num, elevated: num }),
  alerts: object({
    load_index_min: num,
    queue_trend_min_pct: num,
    queue_trend_min_queue_now: num,
  }),
  recommendations: object({
    region_top_fraction: num,
    min_wait_delta_days: num,
    max_alternatives: num,
    min_registrations_28d: num,
  }),
  data_source: object({
    publisher: str,
    description: str,
    period: str,
    datasets: array(str),
    caveats: array(str),
  }),
});
export type Config = Infer<typeof configSchema>;

export const meSchema = object({
  label: str,
  role: literal("viewer", "specialist", "admin"),
  role_label: str,
  permissions: array(str),
});
export type Me = Infer<typeof meSchema>;
