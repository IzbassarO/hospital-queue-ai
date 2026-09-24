/** fetch stub answering /api/v1 requests with real responses captured from the running API (src/test/fixtures). */
import { vi } from "vitest";

import card from "./fixtures/card_ZIQ9_241.json";
import dictionaries from "./fixtures/dictionaries.json";
import health from "./fixtures/health.json";
import overview from "./fixtures/overview.json";

export const fixtures = { card, dictionaries, health, overview };

const ROUTES: [RegExp, unknown][] = [
  [/\/api\/v1\/health$/, health],
  [/\/api\/v1\/overview$/, overview],
  [/\/api\/v1\/dictionaries$/, dictionaries],
  [/\/api\/v1\/hospitals\/ZIQ9\/profiles\/241$/, card],
];

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function mockApi() {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const hit = ROUTES.find(([re]) => re.test(url.split("?")[0]));
    if (!hit) return jsonResponse({ detail: `Not found: ${url}` }, 404);
    return jsonResponse(hit[1]);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
