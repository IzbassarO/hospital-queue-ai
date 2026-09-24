/** Flat projection of Kazakhstan for the SVG map: equirectangular, corrected for latitude 48°. */
import legacyRings from "./kaz-regions.json";
import currentRings from "./kaz-regions-2022.json";
import type { LonLat } from "./places";

/**
 * Which outlines the map draws. "2022": the twenty current regions from OpenStreetMap (incl. Abai, Jetisu,
 * Ulytau and Shymkent). "legacy": the sixteen pre-2022 polygons from Natural Earth, kept on disk as a fallback.
 */
export const MAP_VARIANT: "2022" | "legacy" = "2022";

export const MAP_W = 1000;
const LON0 = 46.4;
const LON1 = 87.6;
const LAT0 = 40.4;
const LAT1 = 55.6;
const COS48 = 0.669;
export const MAP_H = Math.round(
  (MAP_W / ((LON1 - LON0) * COS48)) * (LAT1 - LAT0),
);

export function project([lon, lat]: LonLat): [number, number] {
  const x = ((lon - LON0) / (LON1 - LON0)) * MAP_W;
  const y = ((LAT1 - lat) / (LAT1 - LAT0)) * MAP_H;
  return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
}

export interface RegionShape {
  code: string;
  d: string;
  centroid: [number, number];
}

function ringPath(ring: number[][]): string {
  return (
    ring
      .map((p, i) => {
        const [x, y] = project([p[0], p[1]]);
        return `${i === 0 ? "M" : "L"}${x} ${y}`;
      })
      .join("") + "Z"
  );
}

type RawRegion = { code: string; rings: number[][][] };
const RAW: RawRegion[] = (
  MAP_VARIANT === "2022" ? currentRings : legacyRings
) as RawRegion[];

/** Ray casting in lon/lat against every ring of the (pre-2022) polygon of a region. */
export function pointInRegion(code: string, [lon, lat]: LonLat): boolean {
  const region = RAW.find((r) => r.code === code);
  if (!region) return false;
  return region.rings.some((ring) => {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      const crosses =
        yi > lat !== yj > lat &&
        lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
      if (crosses) inside = !inside;
    }
    return inside;
  });
}

/** Region outlines projected once at module load (16 pre-2022 polygons, ~1.3 k points). */
export const REGION_SHAPES: RegionShape[] = RAW.map((r) => {
  const largest = [...r.rings].sort((a, b) => b.length - a.length)[0] ?? [];
  const sx = largest.reduce((s, p) => s + p[0], 0) / (largest.length || 1);
  const sy = largest.reduce((s, p) => s + p[1], 0) / (largest.length || 1);
  return {
    code: r.code,
    d: r.rings.map(ringPath).join(""),
    centroid: project([sx, sy]),
  };
});
