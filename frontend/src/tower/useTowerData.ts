/**
 * Data of the control centre: the published overview and signals (real), the registry (real) and the synthetic
 * layer derived from them (hospital positions, queue). The model is memoised once every query has settled.
 */
import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../api/client";
import { useOperationalOverview, useSignals } from "../api/operational";
import type { SignalView } from "../api/operational-adapters";
import { useDictionaries, useOverview } from "../api/queries";
import { shortenOrganization } from "../demo/useDemoSubject";
import { REGION_CAPITALS } from "./geo/places";
import type { AlertSeed } from "./sim/simulation";
import {
  generatePatients,
  placeHospitals,
  type HospitalPoint,
  type SyntheticPatient,
} from "./synthetic";

export interface TowerHospital extends HospitalPoint {
  name: string;
  regionName: string;
  severity: "HIGH" | "ELEVATED" | null;
  signals: SignalView[];
}

export interface RegionSummary {
  code: string;
  name: string;
  total: number;
  high: number;
}

export interface TowerModel {
  origin: string;
  published: string;
  snapshotId: string;
  hospitals: TowerHospital[];
  byOrg: Map<string, TowerHospital>;
  regions: RegionSummary[];
  regionByCode: Map<string, RegionSummary>;
  profileName: (code: string) => string;
  regionName: (code: string) => string;
  alerts: AlertSeed[];
  patients: SyntheticPatient[];
  counts: { total: number; high: number; elevated: number; hospitals: number };
  dailyBase: number;
  outageRegion: string;
  /** national median wait of the mart (days), the fallback when a hospital × profile has no card */
  nationalWait: number | null;
}

const SEVERITY_RANK: Record<string, number> = { HIGH: 2, ELEVATED: 1 };
const ALERT_LIMIT = 60;
const WATCH_LIMIT = 24;

export function useTowerData() {
  const overview = useOperationalOverview();
  const mart = useOverview();
  const dictionaries = useDictionaries();
  const high = useSignals({ severity: "HIGH", limit: 500, offset: 0 });
  const elevated = useSignals({ severity: "ELEVATED", limit: 500, offset: 0 });
  // Historical wait and queue per hospital × profile of the alert candidates (legacy mart cards; 404 = no card).
  const pairs = useMemo(() => {
    const readable = (s: SignalView) => (s.rawForecast ?? 0) >= 0.5;
    const seen = new Set<string>();
    const out: { org: string; profile: string }[] = [];
    for (const s of [
      ...(high.data?.items ?? []),
      ...(elevated.data?.items ?? []),
    ]) {
      if (!s.org || !s.profile || !readable(s)) continue;
      const key = `${s.org}:${s.profile}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ org: s.org, profile: s.profile });
    }
    return out.slice(0, 120);
  }, [high.data, elevated.data]);
  const cards = useQueries({
    queries: pairs.map((p) => ({
      queryKey: ["hospital-card", p.org, p.profile],
      queryFn: async () => {
        try {
          const card = await api.hospitalCard(p.org, p.profile);
          return {
            key: `${p.org}:${p.profile}`,
            medianWait: card.status.median_wait_28d,
            queueNow: card.status.queue_now,
          };
        } catch {
          return {
            key: `${p.org}:${p.profile}`,
            medianWait: null,
            queueNow: null,
          };
        }
      },
      staleTime: Infinity,
      retry: false,
    })),
  });
  const cardsPending = cards.some((c) => c.isPending);
  const cardSig = cards
    .map((c) =>
      c.data ? `${c.data.key}=${c.data.medianWait}/${c.data.queueNow}` : "?",
    )
    .join("|");
  const waitByKey = useMemo(() => {
    const m = new Map<
      string,
      { medianWait: number | null; queueNow: number | null }
    >();
    for (const c of cards) if (c.data) m.set(c.data.key, c.data);
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardSig]);
  const isPending =
    overview.isPending ||
    dictionaries.isPending ||
    high.isPending ||
    elevated.isPending ||
    mart.isPending ||
    (pairs.length > 0 && cardsPending);
  const error =
    overview.error ?? dictionaries.error ?? high.error ?? elevated.error;

  const model = useMemo<TowerModel | null>(() => {
    if (!overview.data || !dictionaries.data || !high.data || !elevated.data)
      return null;
    if (pairs.length > 0 && cardsPending) return null;
    if (mart.isPending) return null;
    const dict = dictionaries.data;
    const regionName = (code: string) =>
      dict.regions.find((r) => r.code === code)?.name ?? code;
    const profileName = (code: string) =>
      dict.profiles.find((p) => p.code === code)?.name ?? code;
    const seen = new Set<string>();
    const signals = [...high.data.items, ...elevated.data.items].filter((s) => {
      if (seen.has(s.id)) return false;
      seen.add(s.id);
      return true;
    });
    const signalsByOrg = new Map<string, SignalView[]>();
    for (const s of signals) {
      if (!s.org) continue;
      const list = signalsByOrg.get(s.org) ?? [];
      list.push(s);
      signalsByOrg.set(s.org, list);
    }
    const points = placeHospitals(dict.organizations);
    const hospitals: TowerHospital[] = dict.organizations.map((o) => {
      const own = (signalsByOrg.get(o.code) ?? []).sort(
        (a, b) =>
          (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0) ||
          (a.rank ?? 1e9) - (b.rank ?? 1e9),
      );
      const top = own[0]?.severity;
      return {
        ...(points.get(o.code) as HospitalPoint),
        name: shortenOrganization(o.name),
        regionName: regionName(o.region_code ?? ""),
        severity: top === "HIGH" || top === "ELEVATED" ? top : null,
        signals: own,
      };
    });
    const byOrg = new Map(hospitals.map((h) => [h.org, h]));
    const regions: RegionSummary[] = overview.data.regions.map((r) => ({
      code: r.code,
      name: regionName(r.code),
      total: r.counts.total,
      high: r.counts.high,
    }));
    const regionByCode = new Map(regions.map((r) => [r.code, r]));
    const seedOf = (s: SignalView): AlertSeed => ({
      id: s.id,
      org: s.org ?? "",
      region: s.region ?? "",
      profile: s.profile ?? "",
      hospitalName: byOrg.get(s.org ?? "")?.name ?? s.org ?? "",
      profileName: profileName(s.profile ?? ""),
      regionName: regionName(s.region ?? ""),
      severity: s.severity,
      rank: s.rank ?? null,
      central: s.rawForecast ?? null,
      threshold: s.rawThreshold ?? null,
      lower: s.rawInterval?.[0] ?? null,
      upper: s.rawInterval?.[1] ?? null,
      coverage: s.rawInterval ? "80%" : null,
      crossing: s.rawCrossing ?? null,
      lead: s.rawLeadDays ?? null,
      support: s.support,
      reasons: s.reasons,
      medianWait: waitByKey.get(`${s.org}:${s.profile}`)?.medianWait ?? null,
      queueNow: waitByKey.get(`${s.org}:${s.profile}`)?.queueNow ?? null,
    });
    const byRank = (a: SignalView, b: SignalView) =>
      (a.rank ?? 1e9) - (b.rank ?? 1e9);
    // Presentation filter only: series whose whole daily flow rounds to zero make no readable notification.
    const readable = (s: SignalView) => (s.rawForecast ?? 0) >= 0.5;
    const readableHigh = signals
      .filter((s) => s.severity === "HIGH" && readable(s))
      .sort(byRank)
      .slice(0, ALERT_LIMIT);
    const readableElevated = signals
      .filter((s) => s.severity === "ELEVATED" && readable(s))
      .sort(byRank)
      .slice(0, Math.max(WATCH_LIMIT, ALERT_LIMIT - readableHigh.length));
    const alerts = [...readableHigh, ...readableElevated].map(seedOf);
    const origin = overview.data.snapshot.origin;
    const nationalWait = mart.data?.national.median_wait_28d ?? null;
    const patients = generatePatients(alerts, origin, nationalWait ?? 10);
    // Outage scenario: the region with the most hospitals among the alerts, so the effect is visible.
    const perRegion = new Map<string, number>();
    for (const a of alerts)
      perRegion.set(a.region, (perRegion.get(a.region) ?? 0) + 1);
    const outageRegion =
      [...perRegion.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ??
      Object.keys(REGION_CAPITALS)[0];
    const registrations = mart.data?.national.registrations_28d ?? null;
    return {
      origin,
      published: overview.data.snapshot.published,
      snapshotId: overview.data.snapshot.id,
      hospitals,
      byOrg,
      regions,
      regionByCode,
      profileName,
      regionName,
      alerts,
      patients,
      counts: {
        total: overview.data.counts.total,
        high: overview.data.counts.high,
        elevated: overview.data.counts.severity[1]?.value ?? 0,
        hospitals: dict.organizations.length,
      },
      dailyBase: registrations ? Math.round(registrations / 28) : 7400,
      outageRegion,
      nationalWait,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    overview.data,
    dictionaries.data,
    high.data,
    elevated.data,
    mart.data,
    waitByKey,
    cardsPending,
  ]);

  return { model, isPending, error, refetch: () => void overview.refetch() };
}
