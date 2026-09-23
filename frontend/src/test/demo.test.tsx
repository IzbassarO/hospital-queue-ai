/** Guided decision journey behaviour: navigation, real default subject, human language, evidence, boundaries. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "../routes";
import { t } from "../i18n";
import { SCENES } from "../demo/journey";
import * as d from "./demoFixtures";
import { jsonResponse } from "./mockApi";
import { operationalMock, type Override } from "./operationalMock";
import * as f from "./operationalFixtures";

const base = "/api/v1";
function demoMock(override?: Override) {
  return operationalMock((url) => {
    const overridden = override?.(url);
    if (overridden) return overridden;
    const path = url.pathname.replace(base, "");
    if (path === "/dictionaries") return jsonResponse(d.demoDictionaries);
    if (path === "/operational-intelligence/overview")
      return jsonResponse(d.demoOverview);
    if (path === "/operational-intelligence/signals") {
      const items =
        url.searchParams.get("region") === "39"
          ? d.regionSignals
          : [d.demoSignal, ...d.regionSignals.slice(1)];
      const limit = Number(url.searchParams.get("limit") ?? 20);
      return jsonResponse({
        items: items.slice(0, limit),
        total: 2521,
        limit,
        offset: 0,
      });
    }
    if (path === `/operational-intelligence/signals/${d.DEMO_SIGNAL_ID}`)
      return jsonResponse(d.demoSignal);
    if (
      path ===
      `/operational-intelligence/signals/${d.DEMO_SIGNAL_ID}/explanation`
    )
      return jsonResponse(d.demoExplanation);
    if (path === "/operational-intelligence/regions/39")
      return jsonResponse(d.demoRegion);
    if (path === "/operational-intelligence/forecasts")
      return jsonResponse({
        items: d.demoForecast,
        total: 14,
        limit: 500,
        offset: 0,
      });
    if (path === "/hospitals/000V/profiles/391")
      return jsonResponse(d.legacyCard);
    if (path === "/review-evidence/overview")
      return jsonResponse(d.reviewOverview);
    if (path === `/review-evidence/signals/${d.DEMO_SIGNAL_ID}/stress-test`)
      return jsonResponse(d.stressTest);
    if (
      path ===
      `/review-evidence/signals/${d.DEMO_SIGNAL_ID}/decision-alternatives`
    )
      return jsonResponse(d.demoAlternatives);
    if (path === "/review-evidence/decision-alternatives")
      return jsonResponse({
        items: [d.exampleSummary],
        total: 1,
        limit: 50,
        offset: 0,
      });
    if (
      path === `/review-evidence/decision-alternatives/${d.exampleSet.set_id}`
    )
      return jsonResponse(d.exampleSet);
    if (path === "/model-assurance/capabilities")
      return jsonResponse(d.demoCapabilities);
    return undefined;
  });
}
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
let fetchMock: ReturnType<typeof demoMock>;
const called = (path: string) =>
  fetchMock.mock.calls
    .map(([url]) => new URL(String(url)))
    .filter((u) => u.pathname === `${base}${path}`);
let reducedMotion = false;
beforeEach(() => {
  fetchMock = demoMock();
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("prefers-reduced-motion") && reducedMotion,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});
afterEach(() => {
  reducedMotion = false;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.getElementById("root")?.remove();
});

/** Text of the primary surface: everything except technical disclosures and explicit non-claim blocks. */
function primaryText(): string {
  const main = document.querySelector("main");
  if (!main) return "";
  const clone = main.cloneNode(true) as HTMLElement;
  clone
    .querySelectorAll("[data-technical], [data-nonclaim], svg title")
    .forEach((el) => el.remove());
  return clone.textContent ?? "";
}
const MACHINE_TOKEN =
  /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b|\b[a-z0-9]+(?:_[a-z0-9]+){2,}\b/;
const FORBIDDEN = [
  /рекоменд/i,
  /маршрутиз/i,
  /оптимиз/i,
  /планирован\S* (мощност|вместимост)/i,
  /свободн\S* кой/i,
  /занятост/i,
  /цифров\S* двойник/i,
  /digital twin/i,
  /causal benefit/i,
  /capacity optimizer/i,
  /patient router/i,
  /AI recommender/i,
  /High flow pressure expected/i,
];

describe("Guided decision journey", () => {
  it("/ opens the DETECT scene for the published rank-1 signal and speaks Russian", async () => {
    const router = renderAt("/");
    expect(router.state.location.pathname).toBe("/demo/detect");
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: t.demo.detect.title,
      }),
    ).toBeVisible();
    const request = called("/operational-intelligence/signals")[0];
    expect(Object.fromEntries(request.searchParams)).toEqual({
      limit: "1",
      offset: "0",
    });
    expect(d.demoSignal.signal_id).toBe("cc50965694cb0b6862928df5");
    expect(
      (await screen.findAllByText("Костанайская областная больница")).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Отоларингологические для взрослых").length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("Костанайская область").length).toBeGreaterThan(
      0,
    );
    expect(
      screen.getByText(
        /Потенциальное высокое давление потока — в течение 1 дня/,
      ),
    ).toBeVisible();
    expect(screen.getAllByText("#1").length).toBeGreaterThan(0);
    expect(
      screen.getAllByLabelText(`${t.tower.severity}: ${t.tower.status.HIGH}`)
        .length,
    ).toBeGreaterThan(0);
    await waitFor(() =>
      expect(called("/operational-intelligence/regions/39")).toHaveLength(1),
    );
    expect(await screen.findByText(t.demo.detect.thisSignal)).toBeVisible();
    expect(
      screen.queryByText("High flow pressure expected within 1 day."),
    ).not.toBeInTheDocument();
    expect(primaryText()).not.toMatch(MACHINE_TOKEN);
  });

  it("navigates with the progress bar, Next/Previous and keyboard arrows", async () => {
    const user = userEvent.setup();
    const router = renderAt("/demo/detect");
    await screen.findByRole("heading", { level: 1, name: t.demo.detect.title });
    const nav = screen.getByRole("navigation", { name: t.demo.progress });
    expect(within(nav).getAllByRole("link")).toHaveLength(SCENES.length);
    expect(
      within(nav).getByRole("link", { name: /Обнаружение/ }),
    ).toHaveAttribute("aria-current", "step");
    await user.click(
      screen.getByRole("link", {
        name: `${t.demo.next}: ${t.demo.scenes.understand.label} →`,
      }),
    );
    expect(router.state.location.pathname).toBe("/demo/understand");
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: t.demo.understand.title,
      }),
    ).toBeVisible();
    await user.keyboard("{ArrowRight}");
    expect(router.state.location.pathname).toBe("/demo/test");
    await user.keyboard("{ArrowLeft}");
    expect(router.state.location.pathname).toBe("/demo/understand");
    await user.click(
      screen.getByRole("link", { name: `← ${t.demo.previous}` }),
    );
    expect(router.state.location.pathname).toBe("/demo/detect");
    await user.click(within(nav).getByRole("link", { name: /Доверие/ }));
    expect(router.state.location.pathname).toBe("/demo/trust");
    expect(screen.getByText(t.demo.scene(5, 5))).toBeVisible();
    expect(
      screen.getByRole("link", { name: `${t.demo.openOperations} →` }),
    ).toHaveAttribute("href", "/operations");
  });

  it("UNDERSTAND renders the forecast story, mapped reasons and an evidence drawer without raw enums", async () => {
    const user = userEvent.setup();
    renderAt("/demo/understand");
    await screen.findByRole("heading", {
      level: 1,
      name: t.demo.understand.title,
    });
    const chart = await screen.findByRole("img", {
      name: t.demo.understand.chartTitle,
    });
    await waitFor(() =>
      expect(
        within(chart).getAllByText(/Дата отсчёта|Первое превышение/).length,
      ).toBeGreaterThan(0),
    );
    expect(called("/hospitals/000V/profiles/391")).toHaveLength(1);
    expect(
      screen.getAllByText(t.demo.understand.observed, { exact: false }).length,
    ).toBeGreaterThan(0);
    expect(
      await screen.findByText(
        "Даже нижняя граница калиброванного интервала выше исторического ориентира потока",
      ),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Первое превышение ожидается 18.03.2025, опережение 1 дн.",
      ),
    ).toBeVisible();
    expect(
      screen.getByText(t.demo.understand.knows.calibrated("80,0%")),
    ).toBeVisible();
    expect(screen.getByText(t.demo.understand.askTitle)).toBeVisible();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(primaryText()).not.toMatch(MACHINE_TOKEN);
    await user.click(
      screen.getByRole("button", { name: t.demo.understand.evidenceDrawer }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: t.demo.understand.evidenceDrawer,
    });
    expect(
      await within(dialog).findByText(
        /Опубликован превентивный сигнал уровня «Высокий»/,
      ),
    ).toBeVisible();
    expect(
      within(dialog).getByText("Опубликованный центральный прогноз: 5,9"),
    ).toBeVisible();
    expect(
      within(dialog).getByText("Калиброванный интервал: от 1,4 до 23,7"),
    ).toBeVisible();
    expect(
      within(dialog).getByText(
        "Есть ли более свежие наблюдения для сравнения?",
      ),
    ).toBeVisible();
    expect(
      within(dialog).getByRole("button", { name: t.tower.close }),
    ).toHaveFocus();
    const drawerClone = dialog.cloneNode(true) as HTMLElement;
    drawerClone
      .querySelectorAll("[data-technical]")
      .forEach((el) => el.remove());
    expect(drawerClone.textContent).not.toMatch(MACHINE_TOKEN);
    await user.click(
      within(dialog).getByText(t.demo.understand.technical, {
        selector: "summary",
      }),
    );
    expect(
      within(dialog).getByText(
        /CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD/,
      ),
    ).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("TEST shows published stress outcomes per scenario and switches scenarios", async () => {
    const user = userEvent.setup();
    renderAt("/demo/test");
    await screen.findByRole("heading", { level: 1, name: t.demo.test.title });
    expect(
      called(`/review-evidence/signals/${d.DEMO_SIGNAL_ID}/stress-test`),
    ).toHaveLength(1);
    expect(
      await screen.findByText(
        `${t.demo.test.identity}: ${t.demo.test.identityHint}`,
      ),
    ).toBeVisible();
    const chips = screen.getAllByRole("button", { pressed: true });
    expect(chips[0]).toHaveTextContent("×1,20");
    expect(screen.getByText("5,9 → 7,1")).toBeVisible();
    expect(
      screen.getByText(t.demo.test.networkCells("10,3%", "37 695")),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "×0,90" }));
    expect(screen.getByText("5,9 → 5,3")).toBeVisible();
    expect(
      screen.getByLabelText(`${t.tower.severity}: ${t.tower.status.ELEVATED}`),
    ).toBeVisible();
    expect(screen.getByText(t.demo.test.nonClaims[0])).toBeVisible();
    expect(primaryText()).not.toMatch(MACHINE_TOKEN);
  });

  it("REVIEW shows the engine's abstention for the subject and a verified same-region alternative", async () => {
    renderAt("/demo/review");
    await screen.findByRole("heading", { level: 1, name: t.demo.review.title });
    expect(await screen.findByText(t.demo.review.abstainedTitle)).toBeVisible();
    expect(screen.getByText("до 5% · до 10% · до 25% · до 100%")).toBeVisible();
    expect(screen.getByText("88,6%")).toBeVisible();
    expect(
      screen.getByText(/Ни у одного ряда-приёмника того же профиля/),
    ).toBeVisible();
    const listing = called("/review-evidence/decision-alternatives")[0];
    expect(Object.fromEntries(listing.searchParams)).toMatchObject({
      origin: "2025-03-17",
      region: "39",
      with_alternatives: "true",
    });
    expect(
      await screen.findByText("Костанайский областной кардиологический центр"),
    ).toBeVisible();
    expect(
      screen.getByText("Рудненская городская многопрофильная больница"),
    ).toBeVisible();
    expect(screen.getAllByText("30,3%").length).toBeGreaterThan(0);
    expect(screen.getByText(t.demo.review.verified)).toBeVisible();
    expect(screen.getByText(t.demo.review.noWorsening)).toBeVisible();
    expect(
      screen.getByText("Физическая вместимость не проверялась"),
    ).toBeVisible();
    for (const text of t.demo.review.nonClaims)
      expect(screen.getByText(text)).toBeVisible();
    expect(primaryText()).not.toMatch(MACHINE_TOKEN);
  });

  it("TRUST presents six indicators with real calibration coverage and hides hashes behind provenance", async () => {
    const user = userEvent.setup();
    renderAt("/demo/trust");
    await screen.findByRole("heading", { level: 1, name: t.demo.trust.title });
    expect(
      await screen.findByText(t.demo.trust.indicators.temporal.title),
    ).toBeVisible();
    expect(
      screen.getByText(/на валидации 83%, на финальном тесте 70%/),
    ).toBeVisible();
    expect(
      screen.getByText(
        /Принято возможностей: 4, отклонено: 1, только для оценки: 2/,
      ),
    ).toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(6);
    expect(screen.getAllByText(new RegExp(f.identity))[0]).not.toBeVisible();
    await user.click(
      screen.getByText(t.demo.trust.provenance, { selector: "summary" }),
    );
    expect(screen.getAllByText(new RegExp(f.identity)).length).toBeGreaterThan(
      0,
    );
    expect(
      screen.getByRole("link", { name: `${t.demo.trust.openAssurance} →` }),
    ).toHaveAttribute("href", "/assurance");
  });

  it.each(SCENES)(
    "%s scene contains no forbidden recommendation, routing, capacity or twin claims",
    async (scene) => {
      renderAt(`/demo/${scene}`);
      await waitFor(() =>
        expect(screen.getByRole("heading", { level: 1 })).toBeVisible(),
      );
      await waitFor(
        () => expect(screen.queryAllByText(t.demo.loading)).toHaveLength(0),
        { timeout: 4000 },
      );
      const text = primaryText();
      for (const pattern of FORBIDDEN) expect(text).not.toMatch(pattern);
    },
  );

  it("renders final values immediately under prefers-reduced-motion", async () => {
    reducedMotion = true;
    renderAt("/demo/detect");
    await screen.findByRole("heading", { level: 1, name: t.demo.detect.title });
    const value = await screen.findByText(
      (_, el) =>
        el?.classList.contains("stat-value") === true &&
        el.textContent?.startsWith("5,9") === true,
    );
    expect(value).toBeVisible();
    expect(value).toHaveAttribute(
      "data-final",
      String(d.demoSignal.forecast_value),
    );
  });

  it("explicit ?signal= subject and missing publication are handled", async () => {
    renderAt(`/demo/detect?signal=${d.DEMO_SIGNAL_ID}`);
    expect(
      (await screen.findAllByText("Костанайская областная больница")).length,
    ).toBeGreaterThan(0);
    expect(
      called(`/operational-intelligence/signals/${d.DEMO_SIGNAL_ID}`),
    ).toHaveLength(1);
    document.getElementById("root")?.remove();
    fetchMock = demoMock((url) =>
      url.pathname.endsWith("/operational-intelligence/signals")
        ? jsonResponse({ detail: "No current publication" }, 404)
        : undefined,
    );
    renderAt("/demo/detect");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      t.tower.noPublicationHint,
    );
  });

  it("unpublished stress-test or alternatives never fake a scene", async () => {
    fetchMock = demoMock((url) =>
      url.pathname.includes("/review-evidence/")
        ? jsonResponse({ detail: "no current review-evidence snapshot" }, 404)
        : undefined,
    );
    renderAt("/demo/test");
    expect(await screen.findByText(t.demo.test.notPublished)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "×1,20" }),
    ).not.toBeInTheDocument();
  });

  it("operations view still works at /operations and links back to the guide", async () => {
    renderAt("/operations");
    expect(
      await screen.findByRole("heading", { name: t.tower.title }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: `${t.demo.openGuide} →` }),
    ).toHaveAttribute("href", "/demo/detect");
    expect(
      screen.getByRole("link", { name: t.tower.overview }),
    ).toHaveAttribute("href", "/operations");
  });
});
