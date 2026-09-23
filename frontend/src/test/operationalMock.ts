import { vi } from "vitest";
import { fixtures, jsonResponse } from "./mockApi";
import * as f from "./operationalFixtures";

export type Override = (url: URL) => Response | Promise<Response> | undefined;
export function operationalMock(override?: Override) {
  const mock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = new URL(String(input));
    const overridden = override?.(url);
    if (overridden) return overridden;
    const path = url.pathname.replace("/api/v1", "");
    const base = "/operational-intelligence";
    if (path === "/me") return jsonResponse(fixtures.me);
    if (path === "/dictionaries") return jsonResponse(fixtures.dictionaries);
    if (path === `${base}/overview`) return jsonResponse(f.overview);
    if (path === `${base}/signals`) {
      const items = f.signals.filter((s) =>
        [
          ["severity", s.severity],
          ["support", s.support_status],
          ["region", s.region_code],
          ["profile", s.profile_code],
          ["org", s.org_code],
        ].every(
          ([key, value]) =>
            !url.searchParams.has(key!) || url.searchParams.get(key!) === value,
        ),
      );
      const limit = Number(url.searchParams.get("limit") ?? 20),
        offset = Number(url.searchParams.get("offset") ?? 0);
      return jsonResponse({
        items: items.slice(offset, offset + limit),
        total: items.length,
        limit,
        offset,
      });
    }
    if (path === `${base}/signals/pressure-1`) return jsonResponse(f.signal);
    if (path === `${base}/signals/pressure-1/explanation`)
      return jsonResponse(f.explanation);
    if (path === `${base}/regions/71`)
      return jsonResponse({
        snapshot: f.overview.snapshot,
        region_code: "71",
        counts: f.counts,
        top_signals: f.signals,
        forecast_point_count: 3,
        available_origins: [f.signal.origin],
        available_targets: [f.signal.target],
      });
    if (path === `${base}/hospitals/ZIQ9/profiles/241`)
      return jsonResponse({
        snapshot: f.overview.snapshot,
        org_code: "ZIQ9",
        region_code: "71",
        profile_code: "241",
        counts: f.counts,
        signals: f.signals,
        forecast_point_count: 3,
        available_origins: [f.signal.origin],
        available_targets: [f.signal.target],
      });
    if (path === `${base}/forecasts`) {
      const level = url.searchParams.get("level");
      const point = {
        ...f.forecast,
        level,
        series_id: level === "hospital" ? f.forecast.series_id : `${level}-241`,
        org_code: level === "hospital" ? "ZIQ9" : null,
      };
      return jsonResponse({
        items: [
          point,
          {
            ...point,
            target_date: "2025-04-02",
            horizon: 2,
            central_value: 16,
            raw_quantiles: { ...point.raw_quantiles, p50: 16 },
          },
        ],
        total: 2,
        limit: 500,
        offset: 0,
      });
    }
    if (path === "/model-assurance") return jsonResponse(f.assurance);
    if (path === "/model-assurance/capabilities")
      return jsonResponse(f.capabilities);
    // No fallback to legacy endpoints: migration tests must fail if one is mounted.
    return jsonResponse({ detail: `Unexpected endpoint: ${path}` }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
