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
  type Schema,
  str,
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
