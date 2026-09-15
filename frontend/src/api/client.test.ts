import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { fixtures, jsonResponse, mockApi } from "../test/mockApi";
import { api, ApiError } from "./client";
import {
  alertPageSchema,
  decisionPageSchema,
  decisionSchema,
  dictionariesSchema,
  healthSchema,
  hospitalCardSchema,
  hospitalPageSchema,
  modelsSchema,
  overviewSchema,
  recommendationsSchema,
  referralPageSchema,
  regionDetailSchema,
} from "./types";

afterEach(() => vi.unstubAllGlobals());

describe("API client parses real responses (captured from the running API)", () => {
  it("parses every endpoint the UI calls", async () => {
    mockApi();
    const overview = await api.overview();
    expect(overview.national.code).toBe("KZ");
    expect(overview.regions.length).toBeGreaterThan(0);

    const region = await api.region("71");
    expect(region.profiles.map((p) => p.profile_code)).toContain("241");

    const hospitals = await api.regionHospitals("71", {
      profile: "241",
      limit: 50,
      offset: 0,
    });
    expect(hospitals.items[0]?.org_code).toBe("ZIQ9");

    const card = await api.hospitalCard("ZIQ9", "241");
    expect(card.series.at(-1)?.date).toBe(card.status.as_of_date);
    expect(card.forecast.points).toHaveLength(14);
    expect(
      card.explanation_factors.wait_time[0]?.most_common_value_display,
    ).toBeTruthy();
    // the queue forecast is deliberately not part of the contract
    expect(card.forecast.points[0]).not.toHaveProperty("queue");

    const referrals = await api.referrals("ZIQ9", "241", {
      sort: "risk",
      limit: 20,
      offset: 0,
    });
    expect(
      referrals.items[0]?.explanation.refusal_risk?.[0]?.value_display,
    ).toBeTruthy();

    const recommendations = await api.recommendations("ZIQ9", "241");
    expect(recommendations.alternatives.length).toBeGreaterThan(0);

    const decisions = await api.decisions({
      org: "ZIQ9",
      profile: "241",
      limit: 100,
      offset: 0,
    });
    expect(decisions.items[0]?.action).toBe("confirm");

    expect(
      (await api.alerts({ limit: 50, offset: 0 })).items[0]?.reasons.length,
    ).toBeGreaterThan(0);
    expect((await api.models()).map((m) => m.model_name)).toEqual([
      "wait_time",
      "refusal_risk",
      "load_forecast",
    ]);
    expect((await api.dictionaries()).national_code).toBe("KZ");
    expect((await api.health()).status).toBe("ok");
  });

  it("sends query parameters and the decision body", async () => {
    const fetchMock = mockApi();
    await api.regionHospitals("71", { profile: "241", limit: 50, offset: 50 });
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toMatch(
      /\/api\/v1\/regions\/71\/hospitals\?profile=241&limit=50&offset=50$/,
    );

    fetchMock.mockResolvedValueOnce(
      jsonResponse(fixtures.decisions.items[0], 201),
    );
    const payload = {
      region_code: "71",
      org_code: "ZIQ9",
      profile_code: "241",
      recommendation_id: "rec-v1:historical_median:2025-03-31:ZIQ9:241:ZH7B",
      action: "confirm" as const,
      comment: null,
      actor: "Иванова А.",
    };
    const created = await api.createDecision(payload);
    expect(created.id).toBe(5);
    const init = fetchMock.mock.calls.at(-1)?.[1];
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual(payload);
  });

  it("reports a missing or mistyped field with its path", async () => {
    const broken = structuredClone(fixtures.overview) as {
      national: Record<string, unknown>;
    };
    broken.national.queue_now = "89545";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(broken)),
    );
    const error = await api.overview().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).kind).toBe("shape");
    expect((error as ApiError).message).toContain(
      "national.queue_now: expected number",
    );
  });

  it("reports the URL it tried when the API is down, and the API detail on 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))),
    );
    const down = (await api.overview().catch((e: unknown) => e)) as ApiError;
    expect(down.kind).toBe("network");
    expect(down.url).toMatch(/^http:\/\/.+\/api\/v1\/overview$/);

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "unknown region '00'" }, 404)),
    );
    const missing = (await api
      .region("00")
      .catch((e: unknown) => e)) as ApiError;
    expect(missing.kind).toBe("http");
    expect(missing.status).toBe(404);
    expect(missing.detail).toBe("unknown region '00'");
  });
});

describe("API client schemas match the examples in docs/api.md §6", () => {
  // vitest runs from frontend/; the API contract lives in the repository docs
  const doc = readFileSync(resolve(process.cwd(), "../docs/api.md"), "utf-8");

  /** JSON blocks under each `### \`METHOD /path\`` heading, with the doc's "…" placeholders removed */
  function examples(heading: string): unknown[] {
    const start = doc.indexOf(`### \`${heading}`);
    expect(start, `heading ${heading} in docs/api.md`).toBeGreaterThanOrEqual(
      0,
    );
    const end = doc.indexOf("\n### ", start + 4);
    const section = doc.slice(start, end === -1 ? undefined : end);
    return [...section.matchAll(/```json\n([\s\S]*?)```/g)].map((m) =>
      stripPlaceholders(JSON.parse(m[1] ?? "null")),
    );
  }

  function stripPlaceholders(value: unknown): unknown {
    if (Array.isArray(value)) {
      return value
        .filter((v) => !(typeof v === "string" && v.includes("…")))
        .map(stripPlaceholders);
    }
    if (value && typeof value === "object") {
      return Object.fromEntries(
        Object.entries(value)
          .filter(([k]) => k !== "…")
          .map(([k, v]) => [k, stripPlaceholders(v)]),
      );
    }
    return value;
  }

  it.each([
    ["GET /health", healthSchema, 0],
    ["GET /overview", overviewSchema, 0],
    ["GET /regions/{code}/hospitals", hospitalPageSchema, 0],
    [
      "GET /hospitals/{org}/profiles/{profile}/referrals",
      referralPageSchema,
      0,
    ],
    [
      "GET /hospitals/{org}/profiles/{profile}/recommendations",
      recommendationsSchema,
      0,
    ],
    ["POST /decisions", decisionSchema, 1],
    ["GET /decisions", decisionPageSchema, 0],
    ["GET /alerts", alertPageSchema, 0],
    ["GET /dictionaries", dictionariesSchema, 0],
  ] as const)("%s", (heading, schema, index) => {
    expect(() => schema.parse(examples(heading)[index], heading)).not.toThrow();
  });

  it("captured fixtures cover the shortened doc examples", () => {
    expect(() => regionDetailSchema.parse(fixtures.region)).not.toThrow();
    expect(() => hospitalCardSchema.parse(fixtures.card)).not.toThrow();
    expect(() => modelsSchema.parse(fixtures.models)).not.toThrow();
  });
});
