/**
 * Synthetic layer of the control centre. Everything here is generated in the browser from a fixed seed so the
 * demo is reproducible; nothing is presented as measured. Real inputs: the registry (hospital names, regions,
 * profiles) and the published signals (central forecast, threshold, first crossing, severity).
 */
import {
  GENERATED_TOWNS,
  POLYGON_CHILDREN,
  REGION_CAPITALS,
  TOWNS,
  type LonLat,
} from "./geo/places";
import { MAP_VARIANT, pointInRegion, project } from "./geo/project";

export function hashString(value: string): number {
  let h = 2166136261;
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** mulberry32: small, fast, deterministic. */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Small daily flows need two decimals; anything ≥ 1 reads fine with one. */
export const flowDecimals = (v: number | null): number =>
  v !== null && Math.abs(v) < 1 ? 2 : 1;

export const addDays = (iso: string, days: number): string => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};
export const daysBetween = (from: string, to: string): number =>
  Math.round(
    (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) /
      86400000,
  );

export interface HospitalPoint {
  org: string;
  region: string;
  lonLat: LonLat;
  x: number;
  y: number;
  /** true when a town in the legal name fixed the position */
  placed: boolean;
  /** anchor shared by hospitals of the same town: the map groups them */
  anchor: string;
}

export const polygonForRegion = (region: string): string =>
  MAP_VARIANT === "2022"
    ? region
    : (Object.entries(POLYGON_CHILDREN).find(([, kids]) =>
        kids.includes(region),
      )?.[0] ?? region);

/**
 * Place every hospital inside its region: by the town in its legal name, else around the capital. Positions are
 * jittered deterministically per org and pushed back inside the region polygon, so no dot ever sits outside the
 * country or its region. Hospitals of one town share an anchor and spread on a small disc.
 */
export function placeHospitals(
  orgs: { code: string; name: string; region_code: string | null }[],
): Map<string, HospitalPoint> {
  const groups = new Map<
    string,
    { anchor: LonLat; region: string; placed: boolean; orgs: string[] }
  >();
  for (const o of orgs) {
    const region = o.region_code ?? "";
    const lower = o.name.toLowerCase();
    const polygon = polygonForRegion(region);
    const capital = REGION_CAPITALS[region]?.at ?? [68, 48];
    // Geocoded settlements of this region first (longest stem wins), then the hand-made town list; an anchor
    // outside the hospital's own region is a naming coincidence or a geocoding miss: fall back to the capital.
    const geocoded = GENERATED_TOWNS.filter(
      (g) => g.region === region && lower.includes(g.stem),
    ).sort((a, b) => b.stem.length - a.stem.length)[0];
    const hand = TOWNS.find(([stem]) => lower.includes(stem));
    const candidate: [string, LonLat] | null = geocoded
      ? [geocoded.stem, geocoded.at]
      : hand
        ? [hand[0], hand[1]]
        : null;
    const town =
      candidate && pointInRegion(polygon, candidate[1]) ? candidate : null;
    const byTown = town !== null;
    const anchorAt: LonLat = town ? town[1] : capital;
    const key = `${region}:${town ? town[0] : "capital"}`;
    const group = groups.get(key) ?? {
      anchor: anchorAt,
      region,
      placed: byTown,
      orgs: [],
    };
    group.orgs.push(o.code);
    groups.set(key, group);
  }
  const out = new Map<string, HospitalPoint>();
  for (const [key, group] of groups) {
    const polygon = polygonForRegion(group.region);
    const n = group.orgs.length;
    // Disc radius grows with the group: a capital with 80 hospitals needs room, a district town does not.
    const spread = group.placed
      ? 0.06 + Math.sqrt(n) * 0.045
      : 0.25 + Math.sqrt(n) * 0.09;
    group.orgs.forEach((org, i) => {
      const random = rng(hashString(org));
      const golden = i * 2.399963;
      const radius = spread * Math.sqrt((i + 0.5) / n);
      let lonLat: LonLat = [
        group.anchor[0] +
          Math.cos(golden) * radius * 1.45 +
          (random() - 0.5) * 0.02,
        group.anchor[1] + Math.sin(golden) * radius + (random() - 0.5) * 0.02,
      ];
      // Shrink towards the anchor until the point is inside the region; the anchor itself always is.
      for (let step = 0; step < 6 && !pointInRegion(polygon, lonLat); step++)
        lonLat = [
          group.anchor[0] + (lonLat[0] - group.anchor[0]) * 0.5,
          group.anchor[1] + (lonLat[1] - group.anchor[1]) * 0.5,
        ];
      if (!pointInRegion(polygon, lonLat)) lonLat = group.anchor;
      const [x, y] = project(lonLat);
      out.set(org, {
        org,
        region: group.region,
        lonLat,
        x,
        y,
        placed: group.placed,
        anchor: key,
      });
    });
  }
  return out;
}

export type ScenarioId = "baseline" | "surge" | "season" | "outage";

/** Profiles hit by the seasonal scenario: infectious and paediatric profile names in the registry. */
const SEASONAL = /инфекц|детск|педиатр|пульмон|отоларинг/i;

export interface ScenarioDef {
  id: ScenarioId;
  /** referral multiplier for a series; 1 = as forecast */
  multiplier: (regionCode: string, profileName: string) => number;
  /** national multiplier for the arrivals counter */
  national: number;
  /** region whose data stops arriving */
  outageRegion: string | null;
  /** chance per day that an elevated series escalates on observed flow */
  escalation: number;
}

export function scenarioDef(id: ScenarioId, outageRegion: string): ScenarioDef {
  switch (id) {
    case "surge":
      return {
        id,
        multiplier: () => 1.25,
        national: 1.25,
        outageRegion: null,
        escalation: 0.45,
      };
    case "season":
      return {
        id,
        multiplier: (_r, profile) => (SEASONAL.test(profile) ? 1.5 : 1.03),
        national: 1.12,
        outageRegion: null,
        escalation: 0.3,
      };
    case "outage":
      return {
        id,
        multiplier: () => 1,
        national: 1,
        outageRegion,
        escalation: 0,
      };
    default:
      return {
        id,
        multiplier: () => 1,
        national: 1,
        outageRegion: null,
        escalation: 0.05,
      };
  }
}

export type Urgency = "high" | "medium" | "planned";

/**
 * Below this daily flow a series is too small for "high" attention, whatever its published severity: a hospital
 * that usually sees one referral a week is not in trouble because the forecast says two. Published severity is
 * shown as published; urgency is the product's own reading and applies this floor.
 */
export const URGENCY_FLOOR_PER_DAY = 1;

export function urgencyOf(
  severity: string,
  leadDays: number | null,
  central: number | null = null,
  support: string | null = null,
): Urgency {
  if (central !== null && central < URGENCY_FLOOR_PER_DAY) return "planned";
  const weak = support !== null && support !== "DIRECT_SUPPORTED";
  if (severity === "HIGH" && leadDays !== null && leadDays <= 2 && !weak)
    return "high";
  if (severity === "HIGH" || (leadDays !== null && leadDays <= 5))
    return "medium";
  return "planned";
}

export interface SyntheticPatient {
  id: string;
  org: string;
  region: string;
  profile: string;
  referralDate: string;
  predictedDate: string;
  predictedWait: number;
  urgency: Urgency;
}

/** Pseudonymous queue entries around each alert's crossing window. Counts scale with the central forecast. */
export function generatePatients(
  seeds: {
    org: string;
    region: string;
    profile: string;
    severity: string;
    central: number | null;
    crossing: string | null;
    lead: number | null;
    support?: string;
    medianWait?: number | null;
    queueNow?: number | null;
  }[],
  origin: string,
  fallbackWait = 10,
  seed = 20250317,
): SyntheticPatient[] {
  const random = rng(seed);
  const out: SyntheticPatient[] = [];
  let counter = 1000;
  for (const s of seeds) {
    // Queue size follows the mart's queue for this hospital × profile (a slice of it), else the daily flow.
    const perDay = Math.max(1, Math.min(8, Math.round((s.central ?? 2) / 1.5)));
    const fromQueue =
      s.queueNow != null && s.queueNow > 0
        ? Math.round(Math.min(14, Math.max(2, s.queueNow * 0.12)))
        : null;
    const count =
      fromQueue ?? Math.min(14, 3 + Math.floor(random() * perDay * 2));
    const typicalWait = Math.max(1, Math.round(s.medianWait ?? fallbackWait));
    const crossDay = s.crossing
      ? Math.max(1, daysBetween(origin, s.crossing))
      : 4;
    for (let i = 0; i < count; i++) {
      // Two thirds sit in the forecast window around the crossing, one third further down the queue (≤ 30 days).
      const predictedDay =
        random() < 0.66
          ? Math.max(1, Math.min(14, crossDay + Math.floor(random() * 11) - 2))
          : 15 + Math.floor(random() * 16);
      // Wait = the hospital's historical median for this profile, jittered ±35 % per referral.
      const wait = Math.max(
        1,
        Math.round(typicalWait * (0.65 + random() * 0.7)),
      );
      counter += 1 + Math.floor(random() * 7);
      out.push({
        id: `Н-${String(counter).padStart(4, "0")}`,
        org: s.org,
        region: s.region,
        profile: s.profile,
        referralDate: addDays(origin, predictedDay - wait),
        predictedDate: addDays(origin, predictedDay),
        predictedWait: wait,
        urgency: urgencyOf(s.severity, s.lead, s.central, s.support ?? null),
      });
    }
  }
  return out.sort((a, b) => a.predictedDate.localeCompare(b.predictedDate));
}
