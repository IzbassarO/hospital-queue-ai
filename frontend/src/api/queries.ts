/** TanStack Query hooks, one per endpoint. Data is an as-of snapshot, so it is cached generously. */
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api, ApiError } from "./client";
import type { DecisionCreate } from "./types";

export const queryKeys = {
  overview: ["overview"] as const,
  dictionaries: ["dictionaries"] as const,
  region: (code: string) => ["region", code] as const,
  regionHospitals: (
    code: string,
    profile: string | undefined,
    offset: number,
  ) => ["region", code, "hospitals", profile ?? null, offset] as const,
  card: (org: string, profile: string) =>
    ["hospital", org, profile, "card"] as const,
  referrals: (org: string, profile: string, sort: string, offset: number) =>
    ["hospital", org, profile, "referrals", sort, offset] as const,
  recommendations: (org: string, profile: string) =>
    ["hospital", org, profile, "recommendations"] as const,
  decisions: (org: string, profile: string) =>
    ["decisions", org, profile] as const,
  alerts: (
    region: string | undefined,
    profile: string | undefined,
    status: string | undefined,
    offset: number,
  ) =>
    [
      "alerts",
      region ?? null,
      profile ?? null,
      status ?? null,
      offset,
    ] as const,
  config: ["config"] as const,
  me: ["me"] as const,
  models: ["models"] as const,
};

export const PAGE_SIZE = 50;

/**
 * Keep the previous page on screen (dimmed) while the next page of the SAME list loads; when the filter itself
 * changes (another profile or region) show the skeleton instead, so rows of the old filter never appear under the
 * new title. Keys end with the offset; everything before it is the filter.
 */
function keepWhileSameFilter(key: readonly unknown[]) {
  const filter = JSON.stringify(key.slice(0, -1));
  return <T>(
    previous: T | undefined,
    previousQuery?: { queryKey: readonly unknown[] },
  ) =>
    previousQuery &&
    JSON.stringify(previousQuery.queryKey.slice(0, -1)) === filter
      ? previous
      : undefined;
}
export const REFERRALS_PAGE_SIZE = 20;

export function useOverview() {
  return useQuery({ queryKey: queryKeys.overview, queryFn: api.overview });
}

export function useDictionaries() {
  return useQuery({
    queryKey: queryKeys.dictionaries,
    queryFn: api.dictionaries,
    staleTime: Infinity,
  });
}

export function useRegion(code: string) {
  return useQuery({
    queryKey: queryKeys.region(code),
    queryFn: () => api.region(code),
  });
}

export function useRegionHospitals(
  code: string,
  profile: string | undefined,
  offset: number,
) {
  return useQuery({
    queryKey: queryKeys.regionHospitals(code, profile, offset),
    queryFn: () =>
      api.regionHospitals(code, { profile, limit: PAGE_SIZE, offset }),
    enabled: profile !== undefined,
    placeholderData: keepWhileSameFilter(
      queryKeys.regionHospitals(code, profile, 0),
    ),
  });
}

export function useHospitalCard(org: string, profile: string) {
  return useQuery({
    queryKey: queryKeys.card(org, profile),
    queryFn: () => api.hospitalCard(org, profile),
  });
}

export function useReferrals(
  org: string,
  profile: string,
  sort: "risk" | "wait",
  offset: number,
) {
  return useQuery({
    queryKey: queryKeys.referrals(org, profile, sort, offset),
    queryFn: () =>
      api.referrals(org, profile, { sort, limit: REFERRALS_PAGE_SIZE, offset }),
    placeholderData: keepPreviousData,
  });
}

export function useRecommendations(org: string, profile: string) {
  return useQuery({
    queryKey: queryKeys.recommendations(org, profile),
    queryFn: () => api.recommendations(org, profile),
  });
}

export function useDecisions(org: string, profile: string) {
  return useQuery({
    queryKey: queryKeys.decisions(org, profile),
    queryFn: () => api.decisions({ org, profile, limit: 100, offset: 0 }),
    // decisions are the only data that changes while the app is open
    staleTime: 0,
  });
}

export function useCreateDecision(org: string, profile: string) {
  const client = useQueryClient();
  return useMutation<
    Awaited<ReturnType<typeof api.createDecision>>,
    ApiError,
    DecisionCreate
  >({
    mutationFn: api.createDecision,
    onSuccess: () =>
      client.invalidateQueries({ queryKey: queryKeys.decisions(org, profile) }),
  });
}

export function useAlerts(
  filters: { region?: string; profile?: string; status?: string },
  offset: number,
) {
  const { region, profile, status } = filters;
  return useQuery({
    queryKey: queryKeys.alerts(region, profile, status, offset),
    queryFn: () =>
      api.alerts({ region, profile, status, limit: PAGE_SIZE, offset }),
    placeholderData: keepWhileSameFilter(
      queryKeys.alerts(region, profile, status, 0),
    ),
  });
}

/** Serving parameters and data source; they change only with `make marts`. */
export function useConfig() {
  return useQuery({
    queryKey: queryKeys.config,
    queryFn: api.config,
    staleTime: Infinity,
  });
}

/** The caller's key label and role (GET /me). */
export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: api.me,
    staleTime: Infinity,
    retry: false,
  });
}

export function useModels() {
  return useQuery({
    queryKey: queryKeys.models,
    queryFn: api.models,
    staleTime: Infinity,
  });
}
