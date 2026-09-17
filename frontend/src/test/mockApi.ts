/** fetch stub answering /api/v1 requests with real responses captured from the running API (src/test/fixtures). */
import { vi } from "vitest";

import alerts from "./fixtures/alerts.json";
import card from "./fixtures/card_ZIQ9_241.json";
import config from "./fixtures/config.json";
import decisions from "./fixtures/decisions_ZIQ9_241.json";
import dictionaries from "./fixtures/dictionaries.json";
import health from "./fixtures/health.json";
import hospitals from "./fixtures/hospitals_71_241.json";
import me from "./fixtures/me.json";
import models from "./fixtures/models.json";
import overview from "./fixtures/overview.json";
import recommendations from "./fixtures/recommendations_ZIQ9_241.json";
import referrals from "./fixtures/referrals_ZIQ9_241.json";
import region from "./fixtures/region_71.json";

export const fixtures = {
  alerts,
  card,
  config,
  decisions,
  dictionaries,
  health,
  hospitals,
  me,
  models,
  overview,
  recommendations,
  referrals,
  region,
};

const ROUTES: [RegExp, unknown][] = [
  [/\/api\/v1\/health$/, health],
  [/\/api\/v1\/me$/, me],
  [/\/api\/v1\/config$/, config],
  [/\/api\/v1\/overview$/, overview],
  [/\/api\/v1\/dictionaries$/, dictionaries],
  [/\/api\/v1\/regions\/71$/, region],
  [/\/api\/v1\/regions\/71\/hospitals$/, hospitals],
  [/\/api\/v1\/hospitals\/ZIQ9\/profiles\/241$/, card],
  [/\/api\/v1\/hospitals\/ZIQ9\/profiles\/241\/referrals$/, referrals],
  [
    /\/api\/v1\/hospitals\/ZIQ9\/profiles\/241\/recommendations$/,
    recommendations,
  ],
  [/\/api\/v1\/decisions$/, decisions],
  [/\/api\/v1\/alerts$/, alerts],
  [/\/api\/v1\/models$/, models],
];

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function mockApi() {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = new URL(
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
      );
      if (/\/export$/.test(url.pathname)) {
        const format = url.searchParams.get("format") ?? "xlsx";
        // Node 22's native Response cannot consume jsdom's cross-realm Blob (`object.stream is not a function`).
        // A string is standards-compliant BodyInit in both environments; download() still exercises response.blob().
        return new Response("%PDF-1.4 test", {
          status: 200,
          headers: {
            "Content-Type":
              format === "pdf" ? "application/pdf" : "application/octet-stream",
            "Content-Disposition": `attachment; filename="hqai_card_ZIQ9_241_2025-03-31.${format}"`,
          },
        });
      }
      const match = ROUTES.find(([pattern]) => pattern.test(url.pathname));
      return match
        ? jsonResponse(match[1])
        : jsonResponse({ detail: `no fixture for ${url.pathname}` }, 404);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
