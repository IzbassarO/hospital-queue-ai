import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "../routes";
import { t } from "../i18n";
import { jsonResponse } from "./mockApi";
import * as f from "./operationalFixtures";
import { operationalMock } from "./operationalMock";

function renderAt(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const container = document.createElement("div");
  container.id = "root";
  document.body.appendChild(container);
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
    { container },
  );
  return router;
}
let fetchMock: ReturnType<typeof operationalMock>;
const urls = () => fetchMock.mock.calls.map(([url]) => new URL(String(url)));
const called = (path: string) =>
  urls().filter((u) => u.pathname === `/api/v1${path}`);
beforeEach(() => {
  fetchMock = operationalMock();
});
afterEach(() => {
  // Every route test also rejects accidental legacy metric or artifact calls.
  expect(
    urls().every(
      (u) =>
        u.pathname.startsWith("/api/v1/operational-intelligence/") ||
        [
          "/api/v1/me",
          "/api/v1/dictionaries",
          "/api/v1/model-assurance",
          "/api/v1/model-assurance/capabilities",
        ].includes(u.pathname),
    ),
  ).toBe(true);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.getElementById("root")?.remove();
});
const base = "/operational-intelligence";

describe("Control Tower routes use published operational contracts", () => {
  it("Overview renders operational counts, region matrix, server-ranked signals and national forecast", async () => {
    renderAt("/operations");
    expect(
      await screen.findByRole("heading", { name: t.tower.title }),
    ).toBeVisible();
    const table = await screen.findByRole("table", { name: t.tower.regional });
    expect(
      within(table).getByRole("link", { name: "г. Астана" }),
    ).toHaveAttribute("href", "/regions/71");
    expect(
      within(table)
        .getAllByRole("cell")
        .map((el) => el.textContent),
    ).toEqual(["3", "1", "1"]);
    expect(await screen.findByText("#7")).toBeVisible();
    expect(screen.getByText(t.tower.unknownFreshness)).toBeVisible();
    expect(screen.getByText("роль: специалист")).toBeVisible();
    await waitFor(() => expect(called(`${base}/forecasts`)).toHaveLength(1));
    expect(called(`${base}/overview`)).toHaveLength(1);
    expect(called(`${base}/signals`)[0].searchParams.get("limit")).toBe("5");
    expect(
      Object.fromEntries(called(`${base}/forecasts`)[0].searchParams),
    ).toMatchObject({ level: "national", origin: "2025-03-31" });
  });

  it.each(["/signals", "/alerts"])(
    "%s renders distinct severity/support and preserves deterministic rank",
    async (path) => {
      renderAt(path);
      const cards = await screen.findAllByRole("article");
      expect(
        cards.map((c) => within(c).getByRole("heading").textContent),
      ).toEqual(f.signals.map((s) => s.headline));
      expect(
        within(cards[0]).getByLabelText(
          `${t.tower.severity}: ${t.tower.status.HIGH}`,
        ),
      ).toHaveClass("severity-high");
      expect(
        within(cards[1]).getByLabelText(
          `${t.tower.support}: ${t.tower.status.FALLBACK_LIMITED}`,
        ),
      ).toHaveClass("support-fallback_limited");
      expect(
        within(cards[2]).getByLabelText(
          `${t.tower.support}: ${t.tower.status.UNSUPPORTED}`,
        ),
      ).toHaveClass("support-unsupported");
      expect(
        within(cards[0]).getByRole("link", { name: t.tower.investigate }),
      ).toHaveAttribute("href", "/signals/pressure-1");
      expect(
        screen.getByRole("link", { name: t.tower.signals }),
      ).toHaveAttribute("aria-current", "page");
      expect(called(`${base}/signals`)).toHaveLength(1);
    },
  );

  it("Signals filters are sent to the endpoint, change results and reset paging", async () => {
    const user = userEvent.setup();
    const router = renderAt("/signals?offset=20");
    await screen.findByText(t.tower.noSignals);
    await user.selectOptions(
      screen.getByLabelText(t.tower.severity),
      "ELEVATED",
    );
    await user.selectOptions(
      screen.getByLabelText(t.tower.support),
      "FALLBACK_LIMITED",
    );
    await user.selectOptions(screen.getByLabelText(t.tower.profile), "241");
    await user.selectOptions(screen.getByLabelText(t.tower.region), "71");
    expect(
      await screen.findByRole("heading", { name: f.signals[1].headline }),
    ).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: f.signal.headline }),
    ).not.toBeInTheDocument();
    expect(
      Object.fromEntries(called(`${base}/signals`).at(-1)!.searchParams),
    ).toEqual({
      region: "71",
      profile: "241",
      severity: "ELEVATED",
      support: "FALLBACK_LIMITED",
      limit: "20",
      offset: "0",
    });
    expect(router.state.location.search).not.toContain("offset");
  });

  it("legacy alert status and hospital-filter deep links keep their semantics", async () => {
    const user = userEvent.setup();
    renderAt("/alerts?status=high&org=ZIQ9&profile=241");
    await screen.findByRole("heading", { name: f.signal.headline });
    expect(called(`${base}/signals`)[0].searchParams.get("severity")).toBe(
      "HIGH",
    );
    expect(called(`${base}/signals`)[0].searchParams.get("org")).toBe("ZIQ9");
    await user.selectOptions(
      screen.getByLabelText(t.tower.support),
      "DIRECT_SUPPORTED",
    );
    expect(called(`${base}/signals`).at(-1)!.searchParams.get("severity")).toBe(
      "HIGH",
    );
  });

  it("Signal detail loads its endpoint and shows calibrated evidence, reference, limitations and forecast", async () => {
    const user = userEvent.setup();
    renderAt("/signals/pressure-1");
    expect(
      await screen.findByRole("heading", { level: 1, name: f.signal.headline }),
    ).toBeVisible();
    expect(screen.getByText("FORECAST_ABOVE_REFERENCE")).toBeVisible();
    expect(screen.getByText("Вместимость не проверялась.")).toBeVisible();
    expect(screen.getByText("11,0 – 19,0")).toBeVisible();
    expect(screen.getByText(t.tower.threshold)).toBeVisible();
    await user.click(
      await screen.findByText(t.tower.values, { selector: "summary" }),
    );
    const table = screen.getByRole("table", { name: t.tower.values });
    expect(within(table).getAllByText("11,0 – 19,0")).toHaveLength(2);
    expect(within(table).getAllByText("80,0%")).toHaveLength(2);
    expect(called(`${base}/signals/pressure-1`)).toHaveLength(1);
    expect(
      Object.fromEntries(called(`${base}/forecasts`)[0].searchParams),
    ).toMatchObject({
      org: "ZIQ9",
      profile: "241",
      target: "registrations",
      origin: "2025-03-31",
      level: "hospital",
    });
  });

  it("Explain opens a deterministic evidence drawer with sections, focus trap, Escape and restoration", async () => {
    const user = userEvent.setup();
    renderAt("/signals");
    const button = (
      await screen.findAllByRole("button", { name: t.tower.explain })
    )[0];
    expect(called(`${base}/signals/pressure-1/explanation`)).toHaveLength(0);
    await user.click(button);
    const dialog = await screen.findByRole("dialog", { name: t.tower.explain });
    expect(
      await within(dialog).findByText(f.explanation.summary),
    ).toBeVisible();
    for (const name of [
      t.tower.summary,
      t.tower.reasons,
      t.tower.evidence,
      t.tower.uncertainty,
      t.tower.support,
      t.tower.limitations,
      t.tower.questions,
    ])
      expect(within(dialog).getByRole("heading", { name })).toBeVisible();
    expect(within(dialog).getByText(t.tower.deterministic)).toBeVisible();
    expect(
      within(dialog).getByText(f.explanation.limitations[0]),
    ).toBeVisible();
    expect(
      within(dialog).getByText(f.explanation.suggested_review_questions[0]),
    ).toBeVisible();
    for (const text of [t.tower.human, t.tower.noCapacity, t.tower.noCausal])
      expect(within(dialog).getByText(text)).toBeVisible();
    const close = within(dialog).getByRole("button", { name: t.tower.close });
    expect(close).toHaveFocus();
    expect(document.getElementById("root")!.inert).toBe(true);
    await user.tab({ shift: true });
    expect(
      within(dialog).getByText(t.tower.provenance, { selector: "summary" }),
    ).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
    expect(document.getElementById("root")!.inert).toBe(false);
    expect(called(`${base}/signals/pressure-1/explanation`)).toHaveLength(1);
  });

  it("Region → hospital drill-down calls the new contracts", async () => {
    const user = userEvent.setup();
    fetchMock = operationalMock((url) => {
      if (url.pathname.endsWith("/regions/71"))
        return jsonResponse({
          snapshot: f.overview.snapshot,
          region_code: "71",
          counts: { ...f.counts, high: 23 },
          top_signals: f.signals,
          forecast_point_count: 123,
          available_origins: [f.signal.origin],
          available_targets: [f.signal.target],
        });
      if (url.pathname.endsWith("/hospitals/ZIQ9/profiles/241"))
        return jsonResponse({
          snapshot: f.overview.snapshot,
          org_code: "ZIQ9",
          region_code: "71",
          profile_code: "241",
          counts: { ...f.counts, high: 47 },
          signals: [{ ...f.signal, headline: "Hospital DTO evidence" }],
          forecast_point_count: 456,
          available_origins: [f.signal.origin],
          available_targets: [f.signal.target],
        });
      return undefined;
    });
    const router = renderAt("/regions/71?profile=241");
    expect(
      await screen.findByRole("heading", { level: 1, name: "г. Астана" }),
    ).toBeVisible();
    const hospital = (
      await screen.findAllByRole("link", { name: "Стационар: ZIQ9" })
    )[0];
    expect(called(`${base}/regions/71`)).toHaveLength(1);
    expect(
      screen.getByText(t.tower.high).parentElement?.nextElementSibling,
    ).toHaveTextContent("23");
    expect(screen.getByText(`${t.tower.forecastPoints}: 123`)).toBeVisible();
    await waitFor(() =>
      expect(
        called(`${base}/forecasts`).some(
          (u) =>
            u.searchParams.get("level") === "region" &&
            u.searchParams.get("region") === "71" &&
            u.searchParams.get("profile") === "241",
        ),
      ).toBe(true),
    );
    expect(called(`${base}/signals`)[0].searchParams.get("profile")).toBe(
      "241",
    );
    await user.click(hospital);
    expect(router.state.location.pathname).toBe("/hospitals/ZIQ9/profiles/241");
    expect(
      await screen.findByRole("heading", { level: 1, name: /Стационар ZIQ9/ }),
    ).toBeVisible();
    expect(called(`${base}/hospitals/ZIQ9/profiles/241`)).toHaveLength(1);
    expect(
      await screen.findByRole("heading", { name: "Hospital DTO evidence" }),
    ).toBeVisible();
    expect(
      screen.getByText(t.tower.high).parentElement?.nextElementSibling,
    ).toHaveTextContent("47");
    expect(screen.getByText(`${t.tower.forecastPoints}: 456`)).toBeVisible();
    await waitFor(() =>
      expect(
        called(`${base}/forecasts`).some(
          (u) => u.searchParams.get("level") === "hospital",
        ),
      ).toBe(true),
    );
    expect(screen.getAllByText(t.tower.pressureHint).length).toBeGreaterThan(0);
  });

  it.each(["/assurance", "/models"])(
    "%s renders capability acceptance, product restrictions, governance and identities",
    async (path) => {
      const user = userEvent.setup();
      renderAt(path);
      const rejected = (
        await screen.findByRole("heading", { name: "Rejected Challenger" })
      ).closest("article")!;
      expect(within(rejected).getByText(t.tower.status.REJECTED)).toBeVisible();
      expect(
        within(rejected).getByText(t.tower.status.DO_NOT_PROMOTE),
      ).toBeVisible();
      expect(
        within(rejected).getByText(t.tower.status.NOT_FOR_PRODUCT),
      ).toBeVisible();
      const decision = screen
        .getByRole("heading", { name: "Decision Alternatives" })
        .closest("article")!;
      expect(
        within(decision).getByText(t.tower.status.EVALUATION_ONLY),
      ).toBeVisible();
      expect(within(decision).getByText(t.tower.alternatives)).toBeVisible();
      for (const text of [t.tower.human, t.tower.noCapacity, t.tower.noCausal])
        expect(within(decision).getByText(text)).toBeVisible();
      expect(within(decision).getByText(/fixture-flow/)).not.toBeVisible();
      await user.click(
        within(decision).getByText(t.tower.provenance, { selector: "summary" }),
      );
      expect(within(decision).getByText(/fixture-flow/)).toBeVisible();
      expect(called("/model-assurance")).toHaveLength(2);
      expect(called("/model-assurance/capabilities")).toHaveLength(1);
      expect(
        within(screen.getByRole("navigation", { name: t.nav.main })).getByRole(
          "link",
          { name: t.tower.assurance },
        ),
      ).toHaveAttribute("aria-current", "page");
    },
  );
});

const screens = [
  ["/operations", `${base}/overview`],
  ["/signals", `${base}/signals`],
  ["/signals/pressure-1", `${base}/signals/pressure-1`],
  ["/regions/71", `${base}/regions/71`],
  ["/hospitals/ZIQ9/profiles/241", `${base}/hospitals/ZIQ9/profiles/241`],
  ["/assurance", "/model-assurance"],
];
describe("Deliberate publication states", () => {
  it.each(screens)("%s has a loading state", async (path, endpoint) => {
    fetchMock = operationalMock((url) =>
      url.pathname === `/api/v1${endpoint}`
        ? new Promise<Response>(() => {})
        : undefined,
    );
    renderAt(path);
    expect(
      (await within(screen.getByRole("main")).findAllByText(t.common.loading))
        .length,
    ).toBeGreaterThan(0);
  });
  it.each(screens)(
    "%s handles absent publication / object without crashing",
    async (path, endpoint) => {
      fetchMock = operationalMock((url) =>
        url.pathname === `/api/v1${endpoint}`
          ? jsonResponse({ detail: "No current publication" }, 404)
          : undefined,
      );
      renderAt(path);
      expect(await screen.findByRole("alert")).toHaveTextContent(
        t.tower.noPublicationHint,
      );
    },
  );
  it.each(screens)("%s has a retryable error state", async (path, endpoint) => {
    let failing = true;
    fetchMock = operationalMock((url) =>
      failing && url.pathname === `/api/v1${endpoint}`
        ? jsonResponse({ detail: "Unavailable" }, 503)
        : undefined,
    );
    renderAt(path);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(t.tower.unavailableHint);
    failing = false;
    await userEvent
      .setup()
      .click(within(alert).getByRole("button", { name: t.common.retry }));
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
  });
  it("empty signals and forecasts render understandable states", async () => {
    fetchMock = operationalMock((url) =>
      [`/api/v1${base}/signals`, `/api/v1${base}/forecasts`].includes(
        url.pathname,
      )
        ? jsonResponse({ items: [], total: 0, limit: 500, offset: 0 })
        : undefined,
    );
    renderAt("/operations");
    expect(await screen.findByText(t.tower.noSignals)).toBeVisible();
    expect(await screen.findByText(t.tower.noForecast)).toBeVisible();
  });
  it("degraded and stale metadata remain visible", async () => {
    fetchMock = operationalMock((url) =>
      url.pathname.endsWith("/overview")
        ? jsonResponse({
            ...f.overview,
            snapshot: {
              ...f.overview.snapshot,
              publication_status: "DEGRADED",
              freshness_state: "STALE",
            },
          })
        : undefined,
    );
    renderAt("/operations");
    expect(await screen.findByText(t.tower.degraded)).toBeVisible();
    expect(screen.getByText(t.tower.stale)).toBeVisible();
  });
  it("missing calibrated uncertainty is explicit and raw quantiles are not relabelled as calibrated", async () => {
    fetchMock = operationalMock((url) =>
      url.pathname.endsWith("/forecasts")
        ? jsonResponse({
            items: [
              {
                ...f.forecast,
                calibrated_uncertainty: null,
                uncertainty_status: "UNAVAILABLE",
                calibration_status: "NOT_APPLICABLE",
              },
            ],
            total: 1,
            offset: 0,
            limit: 500,
          })
        : undefined,
    );
    renderAt("/signals/pressure-1");
    expect(await screen.findByText(t.tower.noInterval)).toBeVisible();
    await userEvent
      .setup()
      .click(screen.getByText(t.tower.values, { selector: "summary" }));
    expect(
      within(screen.getByRole("table", { name: t.tower.values })).queryByText(
        "12,0 – 18,0",
      ),
    ).not.toBeInTheDocument();
  });
  it("mismatched forecast publication is not displayed as matching evidence", async () => {
    fetchMock = operationalMock((url) =>
      url.pathname.endsWith("/forecasts")
        ? jsonResponse({
            items: [
              f.forecast,
              {
                ...f.forecast,
                target_date: "2025-04-02",
                horizon: 2,
                publication_identity_sha256: "e".repeat(64),
              },
            ],
            total: 1,
            limit: 500,
            offset: 0,
          })
        : undefined,
    );
    renderAt("/signals/pressure-1");
    expect(await screen.findByText(t.tower.publicationChanged)).toBeVisible();
    expect(screen.queryByText(t.tower.values)).not.toBeInTheDocument();
  });
  it("malformed DTO fails closed into a shape error", async () => {
    fetchMock = operationalMock((url) =>
      url.pathname.endsWith("/overview")
        ? jsonResponse({ snapshot: {}, national: {}, regions: [] })
        : undefined,
    );
    renderAt("/operations");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      t.tower.shapeError,
    );
  });
  it("explanation error stays inside the dismissible drawer", async () => {
    fetchMock = operationalMock((url) =>
      url.pathname.endsWith("/explanation") ? jsonResponse({}, 503) : undefined,
    );
    const user = userEvent.setup();
    renderAt("/signals");
    await user.click(
      (await screen.findAllByRole("button", { name: t.tower.explain }))[0],
    );
    expect(
      await within(screen.getByRole("dialog")).findByRole("alert"),
    ).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("Empty evidence and explanation variants", () => {
  it("EMPTY overview publication and an empty region matrix are explicit", async () => {
    fetchMock = operationalMock((url) =>
      url.pathname.endsWith("/overview")
        ? jsonResponse({
            ...f.overview,
            regions: [],
            snapshot: {
              ...f.overview.snapshot,
              publication_status: "EMPTY",
              forecast_count: 0,
              signal_count: 0,
            },
            national: Object.fromEntries(
              Object.keys(f.counts).map((k) => [k, 0]),
            ),
          })
        : url.pathname.endsWith("/signals") ||
            url.pathname.endsWith("/forecasts")
          ? jsonResponse({ items: [], total: 0, limit: 500, offset: 0 })
          : undefined,
    );
    renderAt("/operations");
    expect(await screen.findByText(t.tower.emptyPublication)).toBeVisible();
    expect(screen.getByText(t.tower.noRegions)).toBeVisible();
  });
  it.each(["/regions/71", "/hospitals/ZIQ9/profiles/241"])(
    "%s keeps empty signals separate from available forecast evidence",
    async (path) => {
      fetchMock = operationalMock((url) =>
        url.pathname.endsWith("/signals")
          ? jsonResponse({ items: [], total: 0, limit: 10, offset: 0 })
          : url.pathname.endsWith("/hospitals/ZIQ9/profiles/241")
            ? jsonResponse({
                snapshot: f.overview.snapshot,
                org_code: "ZIQ9",
                profile_code: "241",
                region_code: "71",
                counts: { ...f.counts, total_signals: 0 },
                signals: [],
                forecast_point_count: 2,
                available_origins: [f.signal.origin],
                available_targets: [f.signal.target],
              })
            : undefined,
      );
      renderAt(path);
      expect(await screen.findByText(t.tower.noSignals)).toBeVisible();
      expect(
        await screen.findByText(t.tower.values, { selector: "summary" }),
      ).toBeVisible();
    },
  );
  it("an empty assurance capability list has an explicit state", async () => {
    fetchMock = operationalMock((url) =>
      url.pathname.endsWith("/capabilities") ? jsonResponse([]) : undefined,
    );
    renderAt("/assurance");
    expect(await screen.findByText(t.tower.noCapabilities)).toBeVisible();
  });
  it("deterministic fallback remains evidence based", async () => {
    fetchMock = operationalMock((url) =>
      url.pathname.endsWith("/explanation")
        ? jsonResponse({
            ...f.explanation,
            generation_mode: "DETERMINISTIC_FALLBACK",
          })
        : undefined,
    );
    const user = userEvent.setup();
    renderAt("/signals");
    await user.click(
      (await screen.findAllByRole("button", { name: t.tower.explain }))[0],
    );
    expect(
      await screen.findByText(t.tower.deterministicFallback),
    ).toBeVisible();
    expect(screen.getByText(f.explanation.summary)).toBeVisible();
  });
  it("an explanation from a changed publication cannot silently describe the old signal", async () => {
    fetchMock = operationalMock((url) =>
      url.pathname.endsWith("/explanation")
        ? jsonResponse({
            ...f.explanation,
            provenance: {
              ...f.explanation.provenance,
              publication_identity_sha256: "e".repeat(64),
            },
          })
        : undefined,
    );
    const user = userEvent.setup();
    renderAt("/signals");
    await user.click(
      (await screen.findAllByRole("button", { name: t.tower.explain }))[0],
    );
    expect(await screen.findByText(t.tower.publicationChanged)).toBeVisible();
    expect(screen.queryByText(f.explanation.summary)).not.toBeInTheDocument();
  });
});

describe("Forecast page boundaries", () => {
  it("does not claim a signal forecast is unpublished when it is on a later page", async () => {
    fetchMock = operationalMock((url) => {
      if (!url.pathname.endsWith("/forecasts")) return undefined;
      const offset = Number(url.searchParams.get("offset"));
      return jsonResponse({
        items:
          offset === 0
            ? Array.from({ length: 500 }, (_, i) => ({
                ...f.forecast,
                series_id: `other-${i}`,
              }))
            : [f.forecast],
        total: 501,
        limit: 500,
        offset,
      });
    });
    const user = userEvent.setup();
    renderAt("/signals/pressure-1");
    expect(await screen.findByText(t.tower.partial)).toBeVisible();
    expect(screen.queryByText(t.tower.noForecast)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: t.common.nextPage }));
    expect(
      await screen.findByText(t.tower.values, { selector: "summary" }),
    ).toBeVisible();
    expect(screen.getByText(t.tower.partial)).toBeVisible();
    expect(called(`${base}/forecasts`).at(-1)!.searchParams.get("offset")).toBe(
      "500",
    );
    expect(
      screen.getByRole("button", { name: t.common.nextPage }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: t.common.prevPage }));
    expect(
      screen.queryByText(t.tower.values, { selector: "summary" }),
    ).not.toBeInTheDocument();
  });
});
