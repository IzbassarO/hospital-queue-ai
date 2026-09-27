/**
 * Where a hospital sits on the map. The registry has no coordinates: a hospital is placed by the town found in its
 * legal name, else around its region's capital, jittered deterministically per org and kept inside the region
 * polygon. Derived from the registry, not synthetic data.
 */
import { hashString, rng } from "../../lib/seeded";
import {
  GENERATED_TOWNS,
  POLYGON_CHILDREN,
  REGION_CAPITALS,
  TOWNS,
  type LonLat,
} from "./places";
import { MAP_VARIANT, pointInRegion, project } from "./project";

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
