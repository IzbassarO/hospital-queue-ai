/** Generated transport → runtime guards → handwritten semantic adapters → query hooks. */
import { useQuery } from "@tanstack/react-query";
import type {
  OperationalSignalsListData,
  OperationalForecastsListData,
} from "./generated";
import { ApiError, buildPath, request } from "./client";
import { array } from "./schema";
import * as s from "./operational-schemas";
import * as a from "./operational-adapters";

export type SignalFilters = NonNullable<OperationalSignalsListData["query"]>;
export type ForecastFilters = NonNullable<
  OperationalForecastsListData["query"]
>;
const base = "/operational-intelligence";
const enc = encodeURIComponent;
export const operationalApi = {
  overview: async () =>
    a.overviewView(
      await request(s.operationalOverviewSchema, `${base}/overview`),
    ),
  signals: async (filters: SignalFilters) => {
    const d = await request(
      s.signalPageSchema,
      buildPath(`${base}/signals`, filters),
    );
    return {
      items: d.items.map(a.signalView),
      total: d.total,
      limit: d.limit,
      offset: d.offset,
    };
  },
  signal: async (id: string) =>
    a.signalView(await request(s.signalSchema, `${base}/signals/${enc(id)}`)),
  explanation: async (id: string) =>
    a.explanationView(
      await request(
        s.explanationSchema,
        `${base}/signals/${enc(id)}/explanation`,
      ),
    ),
  region: async (code: string) =>
    a.regionView(
      await request(s.operationalRegionSchema, `${base}/regions/${enc(code)}`),
    ),
  hospital: async (org: string, profile: string) =>
    a.hospitalView(
      await request(
        s.operationalHospitalSchema,
        `${base}/hospitals/${enc(org)}/profiles/${enc(profile)}`,
      ),
    ),
  forecasts: async (filters: ForecastFilters) => {
    const d = await request(
      s.forecastPageSchema,
      buildPath(`${base}/forecasts`, filters),
    );
    return {
      series: a.forecastGroups(d.items),
      total: d.total,
      limit: d.limit,
      offset: d.offset,
    };
  },
  assurance: async () => {
    const before = await request(s.assuranceSnapshotSchema, "/model-assurance");
    const capabilities = await request(
      array(s.capabilitySchema),
      "/model-assurance/capabilities",
    );
    const after = await request(s.assuranceSnapshotSchema, "/model-assurance");
    if (before.assurance_identity_sha256 !== after.assurance_identity_sha256)
      throw new ApiError(
        "http",
        "/model-assurance",
        "Publication changed",
        409,
      );
    return {
      snapshot: a.assuranceView(after),
      capabilities: capabilities.map(a.capabilityView),
    };
  },
};
const settings = { staleTime: 60_000, retry: false } as const;
export const useOperationalOverview = () =>
  useQuery({
    queryKey: ["operational", "overview"],
    queryFn: operationalApi.overview,
    ...settings,
  });
export const useSignals = (filters: SignalFilters) =>
  useQuery({
    queryKey: ["operational", "signals", filters],
    queryFn: () => operationalApi.signals(filters),
    ...settings,
  });
export const useSignal = (id: string) =>
  useQuery({
    queryKey: ["operational", "signal", id],
    queryFn: () => operationalApi.signal(id),
    ...settings,
  });
export const useExplanation = (id: string) =>
  useQuery({
    queryKey: ["operational", "explanation", id],
    queryFn: () => operationalApi.explanation(id),
    ...settings,
  });
export const useOperationalRegion = (code: string) =>
  useQuery({
    queryKey: ["operational", "region", code],
    queryFn: () => operationalApi.region(code),
    ...settings,
  });
export const useOperationalHospital = (org: string, profile: string) =>
  useQuery({
    queryKey: ["operational", "hospital", org, profile],
    queryFn: () => operationalApi.hospital(org, profile),
    ...settings,
  });
export const useForecasts = (filters: ForecastFilters) =>
  useQuery({
    queryKey: ["operational", "forecasts", filters],
    queryFn: () => operationalApi.forecasts(filters),
    ...settings,
  });
export const useAssurance = () =>
  useQuery({
    queryKey: ["assurance", "current"],
    queryFn: operationalApi.assurance,
    ...settings,
  });
