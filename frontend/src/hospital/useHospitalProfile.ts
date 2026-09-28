/**
 * Everything one hospital × profile needs, from published sources only.
 *
 *  - forecast: the 14 points published at the origin (p50 + calibrated 80 % band) — /operational-intelligence/forecasts
 *  - signal:   the published threshold, first crossing and severity for that series — /operational-intelligence/hospitals/…
 *  - actual:   measured daily registrations from the serving mart — /hospitals/{org}/profiles/{profile}
 *
 * The actual series is hindsight relative to the origin. It is kept in its own field, never merged into the
 * forecast points, so no component can render one as the other by accident.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useForecasts, useOperationalHospital } from "../api/operational";
import type { ForecastSeries, SignalView } from "../api/operational-adapters";

export interface ReplayDay {
  date: string;
  /** published at the origin: the calibrated 80 % interval for this day, when one was published */
  interval: [number, number] | null;
  central: number | null;
  /** measured after the origin — hindsight */
  actual: number | null;
  verdict: "inside" | "above" | "below" | "unknown";
}

const dayVerdict = (
  actual: number | null,
  interval: [number, number] | null,
): ReplayDay["verdict"] => {
  if (actual === null || interval === null) return "unknown";
  if (actual < interval[0]) return "below";
  if (actual > interval[1]) return "above";
  return "inside";
};

export function useHospitalProfile(org: string | null, profile: string | null) {
  const enabled = Boolean(org && profile);
  const forecasts = useForecasts(
    enabled
      ? {
          org: org as string,
          profile: profile as string,
          target: "registrations",
          limit: 14,
        }
      : { limit: 1 },
  );
  const operational = useOperationalHospital(org ?? "", profile ?? "", enabled);
  const card = useQuery({
    queryKey: ["hospital-card", org, profile],
    queryFn: () => api.hospitalCard(org as string, profile as string),
    enabled,
    staleTime: 60_000,
    retry: false,
  });

  const series: ForecastSeries | null = forecasts.data?.series[0] ?? null;
  // The pressure signal of this series, if one was published. Severity and threshold are read, never derived.
  const signal: SignalView | null =
    operational.data?.signals.find((s) => s.target === "registrations") ??
    operational.data?.signals[0] ??
    null;

  const actualByDate = new Map(
    (card.data?.series ?? []).map((p) => [p.date, p.registrations]),
  );
  const replay: ReplayDay[] = (series?.points ?? []).map((point) => {
    const actual = actualByDate.get(point.date) ?? null;
    return {
      date: point.date,
      interval: point.interval,
      central: point.central,
      actual,
      verdict: dayVerdict(actual, point.interval),
    };
  });

  return {
    series,
    signal,
    replay,
    isLoading: forecasts.isLoading || operational.isLoading || card.isLoading,
    /** the forecast is the load-bearing source; a missing card only empties the replay */
    error: forecasts.error ?? operational.error ?? null,
  };
}
