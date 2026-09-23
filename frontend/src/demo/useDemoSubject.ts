/**
 * The subject of the guided journey: by default the published rank-1 signal of the current origin
 * (deterministic rule, nothing is chosen in the browser), or an explicit `?signal=` id.
 */
import { useSearchParams } from "react-router-dom";
import {
  useForecasts,
  useOperationalOverview,
  useOperationalRegion,
  useSignal,
  useSignals,
} from "../api/operational";
import type { SignalView } from "../api/operational-adapters";
import { useDictionaries } from "../api/queries";

export interface SubjectNames {
  region: string;
  hospital: string;
  profile: string;
}

export function useDemoSubject() {
  const [params] = useSearchParams();
  const explicit = params.get("signal") ?? "";
  const overview = useOperationalOverview();
  const ranked = useSignals({ limit: 1, offset: 0 });
  const chosen = useSignal(explicit);
  const dictionaries = useDictionaries();
  const signal: SignalView | undefined = explicit
    ? chosen.data
    : ranked.data?.items[0];
  const isPending = explicit
    ? chosen.isPending
    : ranked.isPending || overview.isPending;
  const error = explicit ? chosen.error : (ranked.error ?? overview.error);
  const region = useOperationalRegion(signal?.region ?? "");
  const forecast = useForecasts({
    origin: signal?.origin,
    org: signal?.org ?? undefined,
    region: signal?.region ?? undefined,
    profile: signal?.profile ?? undefined,
    target: signal?.target,
    level: signal?.org ? "hospital" : signal?.region ? "region" : "national",
    limit: 500,
    offset: 0,
  });
  const names = useNames(signal?.region, signal?.org, signal?.profile);
  const series = forecast.data?.series.find(
    (s) => s.seriesId === signal?.seriesId,
  );
  return {
    signal,
    names,
    isPending,
    error,
    refetch: () => {
      void overview.refetch();
      void ranked.refetch();
      if (explicit) void chosen.refetch();
    },
    snapshot: overview.data?.snapshot,
    overview: overview.data,
    region: region.data,
    regionQuery: region,
    series,
    forecastQuery: forecast,
    dictionaries: dictionaries.data,
    rankedTotal: ranked.data?.total ?? null,
  };
}

export function useNames(
  region?: string | null,
  org?: string | null,
  profile?: string | null,
): SubjectNames {
  const dictionaries = useDictionaries();
  return {
    region:
      dictionaries.data?.regions.find((r) => r.code === region)?.name ??
      region ??
      "",
    hospital: hospitalName(dictionaries.data?.organizations, org),
    profile:
      dictionaries.data?.profiles.find((p) => p.code === profile)?.name ??
      profile ??
      "",
  };
}

export function hospitalName(
  organizations: { code: string; name: string }[] | undefined,
  org?: string | null,
): string {
  const raw = organizations?.find((o) => o.code === org)?.name;
  return raw ? shortenOrganization(raw) : (org ?? "");
}

/** Registry names are long legal titles; keep the quoted proper name when present. */
export function shortenOrganization(name: string): string {
  const quoted = /[«"]([^»"]+)[»"]/.exec(name);
  return quoted ? quoted[1] : name;
}
