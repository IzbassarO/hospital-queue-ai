/**
 * Data of the control centre: the published overview and signals (real), the registry (real), hospital positions
 * derived from the registry, and, while the synthetic layer is on, the queue generated around the published
 * crossing windows. The model is memoised once every query has settled.
 *
 * Confirmation is checked against the real outcome where one exists: the same hospital cards that supply the
 * historical wait also carry observed daily registrations after the origin (`agg_daily_hospital_profile` through
 * the mart), and those days are handed to the simulation as facts. Only a day the mart does not cover falls back to
 * the synthetic flow, and both are labelled on screen.
 *
 * Materiality is a presentation split, never a change of published values: every HIGH and ELEVATED signal is
 * fetched (all pages), and the ones the publication marks `zero_baseline_low_volume` (threshold 0, a forecast of a
 * few hundredths a day) form the "small flows" layer, shown muted and on request. Everything else is the attention
 * queue: it colours the map, fills the region counts and feeds the notifications.
 */
import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../api/client";
import {
  useAllSignals,
  useIntervalCoverage,
  useOperationalOverview,
} from "../api/operational";
import type { SignalView } from "../api/operational-adapters";
import { useDictionaries, useOverview } from "../api/queries";
import { fmtNumber } from "../lib/format";
import { shortenOrganization } from "../demo/useDemoSubject";
import { placeHospitals, type HospitalPoint } from "./geo/place";
import { REGION_CAPITALS } from "./geo/places";
import type { AlertSeed } from "./sim/simulation";
import {
  generatePatients,
  QUEUE,
  SIMULATION,
  SYNTHETIC_ENABLED,
  type SyntheticPatient,
} from "./synthetic";

export type Severity = "HIGH" | "ELEVATED";
export const LOW_VOLUME = "zero_baseline_low_volume";
/** The publication's own classification: a signal below the materiality floor is a "small flow". */
export const isMaterial = (s: SignalView) => s.rawMateriality !== LOW_VOLUME;

export interface TowerHospital extends HospitalPoint {
  name: string;
  regionName: string;
  /** top published severity among the hospital's material signals (the attention queue) */
  severity: Severity | null;
  /** top published severity among its small-flow signals only; drawn as the muted layer */
  lowVolume: Severity | null;
  signals: SignalView[];
  lowVolumeSignals: SignalView[];
}

export interface RegionSummary {
  code: string;
  name: string;
  /** every published signal of the region (all severities), as in the publication overview */
  total: number;
  /** HIGH + ELEVATED signals of the region in the attention queue */
  attention: number;
  /** HIGH signals of the region in the attention queue */
  highMaterial: number;
  /** HIGH + ELEVATED signals of the region below the materiality floor */
  lowVolume: number;
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
  /** profile codes the registry marks as day hospital: the inbox splits them off by default */
  dayHospitalProfiles: Set<string>;
  alerts: AlertSeed[];
  patients: SyntheticPatient[];
  counts: {
    /** every published signal (all severities), as in the publication overview */
    total: number;
    /** HIGH + ELEVATED signals that pass the materiality floor: the attention queue */
    attention: number;
    /** HIGH signals inside the attention queue */
    highMaterial: number;
    /** ELEVATED signals inside the attention queue */
    elevatedMaterial: number;
    /** HIGH + ELEVATED signals below the materiality floor: the small-flows layer */
    lowVolume: number;
    /** attention-queue signals turned into notifications (the readable ones, by priority, capped) */
    shown: number;
    hospitals: number;
    /** false when a listing had more pages than the bounded fetch reads */
    complete: boolean;
  };
  dailyBase: number;
  outageRegion: string;
  /** national median wait of the mart (days), the fallback when a hospital × profile has no card */
  nationalWait: number | null;
  /** as-of date of the data mart: the date every fact block on screen describes */
  martAsOf: string | null;
}

/** Nominal coverage of the published calibrated interval; the measured one is read from the assurance capability. */
export const NOMINAL_COVERAGE = "80%";

/** What one hospital-card request contributes: historical facts plus the observed daily registrations it carries. */
interface CardFacts {
  key: string;
  medianWait: number | null;
  queueNow: number | null;
  backlogDays: number | null;
  observed: Record<string, number>;
}

/** Observed registrations strictly after the origin: the real outcome the forecast can be checked against. */
function afterOrigin(
  observed: Record<string, number> | undefined,
  origin: string,
): Record<string, number> | null {
  if (!observed) return null;
  const out: Record<string, number> = {};
  for (const [date, value] of Object.entries(observed))
    if (date > origin) out[date] = value;
  return Object.keys(out).length ? out : null;
}

const SEVERITY_RANK: Record<string, number> = { HIGH: 2, ELEVATED: 1 };
const ALERT_LIMIT = 60;
const WATCH_LIMIT = 24;
/** Presentation filter only: series whose whole daily flow rounds to zero make no readable notification. */
const READABLE_PER_DAY = 0.5;
const readable = (s: SignalView) => (s.rawForecast ?? 0) >= READABLE_PER_DAY;
const topSeverity = (list: SignalView[]): Severity | null => {
  const top = list[0]?.severity;
  return top === "HIGH" || top === "ELEVATED" ? top : null;
};
const bySeverityThenRank = (a: SignalView, b: SignalView) =>
  (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0) ||
  (a.rank ?? 1e9) - (b.rank ?? 1e9);

export function useTowerData() {
  const overview = useOperationalOverview();
  const mart = useOverview();
  const dictionaries = useDictionaries();
  const coverage = useIntervalCoverage();
  const finalCoverage = coverage?.final ?? null;
  const high = useAllSignals({ severity: "HIGH" });
  const elevated = useAllSignals({ severity: "ELEVATED" });
  // Historical wait and queue per hospital × profile of the alert candidates (legacy mart cards; 404 = no card).
  const pairs = useMemo(() => {
    const seen = new Set<string>();
    const out: { org: string; profile: string }[] = [];
    for (const s of [
      ...(high.data?.items ?? []),
      ...(elevated.data?.items ?? []),
    ]) {
      if (!s.org || !s.profile || !isMaterial(s) || !readable(s)) continue;
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
            backlogDays: card.status.backlog_days,
            observed: Object.fromEntries(
              card.series.map((d) => [d.date, d.registrations]),
            ) as Record<string, number>,
          };
        } catch {
          return {
            key: `${p.org}:${p.profile}`,
            medianWait: null,
            queueNow: null,
            backlogDays: null,
            observed: {} as Record<string, number>,
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
      c.data
        ? `${c.data.key}=${c.data.medianWait}/${c.data.queueNow}/${c.data.backlogDays}/${Object.keys(c.data.observed).length}`
        : "?",
    )
    .join("|");
  const cardByKey = useMemo(() => {
    const m = new Map<string, CardFacts>();
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
    const all = [...high.data.items, ...elevated.data.items].filter((s) => {
      if (seen.has(s.id)) return false;
      seen.add(s.id);
      return true;
    });
    const material = all.filter(isMaterial);
    const lowVolume = all.filter((s) => !isMaterial(s));
    const groupByOrg = (list: SignalView[]) => {
      const m = new Map<string, SignalView[]>();
      for (const s of list) {
        if (!s.org) continue;
        const own = m.get(s.org) ?? [];
        own.push(s);
        m.set(s.org, own);
      }
      for (const own of m.values()) own.sort(bySeverityThenRank);
      return m;
    };
    const materialByOrg = groupByOrg(material);
    const lowVolumeByOrg = groupByOrg(lowVolume);
    const points = placeHospitals(dict.organizations);
    const hospitals: TowerHospital[] = dict.organizations.map((o) => {
      const own = materialByOrg.get(o.code) ?? [];
      const small = lowVolumeByOrg.get(o.code) ?? [];
      return {
        ...(points.get(o.code) as HospitalPoint),
        name: shortenOrganization(o.name),
        regionName: regionName(o.region_code ?? ""),
        severity: topSeverity(own),
        lowVolume: topSeverity(small),
        signals: own,
        lowVolumeSignals: small,
      };
    });
    const byOrg = new Map(hospitals.map((h) => [h.org, h]));
    const perRegion = (
      list: SignalView[],
      pick: (s: SignalView) => boolean,
    ) => {
      const m = new Map<string, number>();
      for (const s of list)
        if (s.region && pick(s)) m.set(s.region, (m.get(s.region) ?? 0) + 1);
      return m;
    };
    const attentionByRegion = perRegion(material, () => true);
    const highByRegion = perRegion(material, (s) => s.severity === "HIGH");
    const lowVolumeByRegion = perRegion(lowVolume, () => true);
    const regions: RegionSummary[] = overview.data.regions.map((r) => ({
      code: r.code,
      name: regionName(r.code),
      total: r.counts.total,
      attention: attentionByRegion.get(r.code) ?? 0,
      highMaterial: highByRegion.get(r.code) ?? 0,
      lowVolume: lowVolumeByRegion.get(r.code) ?? 0,
    }));
    const regionByCode = new Map(regions.map((r) => [r.code, r]));
    const origin = overview.data.snapshot.origin;
    const card = (s: SignalView) => cardByKey.get(`${s.org}:${s.profile}`);
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
      coverage: s.rawInterval ? NOMINAL_COVERAGE : null,
      coverageFinal:
        s.rawInterval && finalCoverage !== null
          ? `${fmtNumber(finalCoverage * 100, 0)}%`
          : null,
      crossing: s.rawCrossing ?? null,
      lead: s.rawLeadDays ?? null,
      support: s.support,
      reasons: s.reasons,
      medianWait: card(s)?.medianWait ?? null,
      queueNow: card(s)?.queueNow ?? null,
      backlogDays: card(s)?.backlogDays ?? null,
      observed: afterOrigin(card(s)?.observed, origin),
    });
    const byRank = (a: SignalView, b: SignalView) =>
      (a.rank ?? 1e9) - (b.rank ?? 1e9);
    const readableHigh = material
      .filter((s) => s.severity === "HIGH" && readable(s))
      .sort(byRank)
      .slice(0, ALERT_LIMIT);
    const readableElevated = material
      .filter((s) => s.severity === "ELEVATED" && readable(s))
      .sort(byRank)
      .slice(0, Math.max(WATCH_LIMIT, ALERT_LIMIT - readableHigh.length));
    const alerts = [...readableHigh, ...readableElevated].map(seedOf);
    const nationalWait = mart.data?.national.median_wait_28d ?? null;
    const patients = SYNTHETIC_ENABLED
      ? generatePatients(
          alerts,
          origin,
          nationalWait ?? QUEUE.wait.fallbackDays,
        )
      : [];
    // Outage scenario: the region with the most hospitals among the alerts, so the effect is visible.
    const alertsPerRegion = new Map<string, number>();
    for (const a of alerts)
      alertsPerRegion.set(a.region, (alertsPerRegion.get(a.region) ?? 0) + 1);
    const outageRegion =
      [...alertsPerRegion.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ??
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
      dayHospitalProfiles: new Set(
        dict.profiles.filter((p) => p.is_day_hospital).map((p) => p.code),
      ),
      alerts,
      patients,
      counts: {
        total: overview.data.counts.total,
        attention: material.length,
        highMaterial: material.filter((s) => s.severity === "HIGH").length,
        elevatedMaterial: material.filter((s) => s.severity === "ELEVATED")
          .length,
        lowVolume: lowVolume.length,
        shown: alerts.length,
        hospitals: dict.organizations.length,
        complete: high.data.complete && elevated.data.complete,
      },
      dailyBase: registrations
        ? Math.round(registrations / 28)
        : SIMULATION.dailyBaseFallback,
      outageRegion,
      nationalWait,
      martAsOf: mart.data?.as_of_date ?? null,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    overview.data,
    dictionaries.data,
    high.data,
    elevated.data,
    mart.data,
    cardByKey,
    cardsPending,
    finalCoverage,
  ]);

  const refetch = () => {
    void overview.refetch();
    void dictionaries.refetch();
    void high.refetch();
    void elevated.refetch();
    void mart.refetch();
  };
  return { model, isPending, error, refetch };
}
