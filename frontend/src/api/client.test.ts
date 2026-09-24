/** The typed client parses the captured responses of every legacy endpoint the demo still calls. */
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "./client";
import { jsonResponse, mockApi } from "../test/mockApi";

afterEach(() => vi.unstubAllGlobals());

describe("API client parses real responses (captured from the running API)", () => {
  it("parses overview, dictionaries, health and the hospital card", async () => {
    mockApi();
    const overview = await api.overview();
    expect(overview.national.n_hospitals).toBeGreaterThan(0);
    expect(overview.regions.length).toBeGreaterThan(0);
    expect((await api.dictionaries()).national_code).toBe("KZ");
    expect((await api.health()).status).toBe("ok");
    const card = await api.hospitalCard("ZIQ9", "241");
    expect(card.series.length).toBeGreaterThan(0);
  });

  it("classifies HTTP failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "missing API key" }, 401)),
    );
    await expect(api.health()).rejects.toMatchObject({
      kind: "auth",
      status: 401,
    } satisfies Partial<ApiError>);
  });
});
