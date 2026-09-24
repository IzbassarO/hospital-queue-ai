/** Control centre behaviour: real published inputs, the day unfolding, the specialist's tasks, two languages. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "../routes";
import { setLang, t } from "../i18n";
import {
  clearSavedSimulation,
  resetSimulationStore,
} from "../tower/sim/useSimulation";
import { TOUR_KEY } from "../tower/tour-state";
import { closeExplorer, closeSubject } from "../tower/ui";
import * as d from "./demoFixtures";
import { fixtures, jsonResponse } from "./mockApi";
import { operationalMock } from "./operationalMock";

const base = "/api/v1";
const ALL = [d.demoSignal, ...d.regionSignals.slice(1)];
function towerMock() {
  return operationalMock((url) => {
    const path = url.pathname.replace(base, "");
    if (path === "/dictionaries") return jsonResponse(d.demoDictionaries);
    if (path === "/overview") return jsonResponse(fixtures.overview);
    if (path === "/operational-intelligence/overview")
      return jsonResponse(d.demoOverview);
    if (path === "/operational-intelligence/signals") {
      const severity = url.searchParams.get("severity");
      const items = ALL.filter((s) => !severity || s.severity === severity);
      return jsonResponse({
        items,
        total: items.length,
        limit: 500,
        offset: 0,
      });
    }
    if (path === "/specialist-decisions" && url.searchParams.has("origin"))
      return jsonResponse({ items: [], total: 0, limit: 500, offset: 0 });
    if (path === "/specialist-decisions")
      return jsonResponse(
        {
          id: 1,
          created_at: "2026-09-23T21:00:00Z",
          origin: "2025-03-17",
          sim_day: 1,
          subject_kind: "alert",
          subject_id: "x",
          region_code: null,
          org_code: null,
          profile_code: null,
          action: "accept",
          comment: null,
          actor: null,
          idempotency_key: null,
          api_key_label: "test",
        },
        201,
      );
    if (path === "/assistant/status")
      return jsonResponse({ configured: false, provider: null, model: null });
    if (path === "/operational-intelligence/forecasts")
      return jsonResponse({
        items: d.demoForecast,
        total: 14,
        limit: 500,
        offset: 0,
      });
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
function primaryText(): string {
  const main = document.querySelector("main");
  const clone = main?.cloneNode(true) as HTMLElement | undefined;
  clone
    ?.querySelectorAll("[data-technical], [data-nonclaim], svg title")
    .forEach((el) => el.remove());
  return clone?.textContent ?? "";
}
const FORBIDDEN = [
  /рекоменд/i,
  /маршрутиз/i,
  /оптимиз/i,
  /свободн\S* кой/i,
  /цифров\S* двойник/i,
];
const MACHINE_WORD = /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b/;

let fetchMock: ReturnType<typeof towerMock>;
beforeEach(() => {
  fetchMock = towerMock();
  resetSimulationStore();
  clearSavedSimulation();
  window.localStorage.setItem(TOUR_KEY, "done");
  closeExplorer();
  closeSubject();
  setLang("ru");
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.getElementById("root")?.remove();
});

const heading = () =>
  screen.findByRole("heading", { level: 1, name: t.control.title });

describe("Control centre", () => {
  it("/ shows the big picture: map, waiting counts, the feed at the origin and the inbox top", async () => {
    const router = renderAt("/");
    expect(router.state.location.pathname).toBe("/");
    expect(await heading()).toBeVisible();
    expect(
      screen.getByRole("img", { name: t.control.map.title }),
    ).toBeVisible();
    const waiting = document.querySelector("dl.waiting") as HTMLElement;
    expect(waiting).toBeVisible();
    expect(within(waiting).getAllByRole("definition").length).toBeGreaterThan(
      3,
    );
    const feed = screen.getByRole("region", { name: t.control.feed.title });
    expect(
      within(feed).getAllByText("Костанайская областная больница").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("region", { name: t.control.priority.title }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: t.control.nav.notifications }),
    ).toHaveAttribute("href", "/notifications");
    expect(
      screen.getByRole("link", { name: t.control.nav.queue }),
    ).toHaveAttribute("href", "/queue");
    expect(
      screen.getByRole("button", { name: t.control.nav.tasks }),
    ).toBeVisible();
    for (const pattern of FORBIDDEN) expect(primaryText()).not.toMatch(pattern);
    expect(primaryText()).not.toMatch(MACHINE_WORD);
  });

  it("the clock walks through the day and stops when the model asks the specialist", async () => {
    renderAt("/");
    await heading();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("button", { name: t.control.sim.play }));
    await act(async () => {
      vi.advanceTimersByTime(6000);
    });
    expect(screen.getByText(t.control.sim.pausedForDecision)).toBeVisible();
    expect(screen.getByText(t.control.sim.day(1))).toBeVisible();
    const feed = screen.getByRole("region", { name: t.control.feed.title });
    expect(
      within(feed).getAllByText(t.control.feed.needsYou).length,
    ).toBeGreaterThan(0);
    const bell = screen.getByRole("button", { name: t.control.nav.tasks });
    expect(bell).toHaveTextContent(/[1-9]/);
  });

  it("a task opens the dialog: verdict with reasons, empty assistant, facts, and the decision is recorded", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await heading();
    await user.click(screen.getByRole("button", { name: t.control.sim.step }));
    await user.click(screen.getByRole("button", { name: t.control.nav.tasks }));
    const explorer = screen.getByRole("complementary", {
      name: t.control.explorer.title,
    });
    const open = await within(explorer).findAllByRole("button", {
      name: t.control.explorer.open,
    });
    await user.click(open[0]);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(t.control.verdict.title)).toBeVisible();
    expect(
      within(dialog).getAllByText(/^(Да|Нет|Пока неясно)$/).length,
    ).toBeGreaterThan(0);
    expect(within(dialog).getByText(t.control.assistant.badge)).toBeVisible();
    expect(within(dialog).getByText(t.control.assistant.stub)).toBeVisible();
    expect(
      within(dialog).getByText(t.control.alerts.facts.title),
    ).toBeVisible();
    await user.type(
      within(dialog).getByLabelText(t.control.decision.comment),
      "согласовано",
    );
    await user.click(
      within(dialog).getAllByRole("button", { name: /^(Принять)$/ })[0],
    );
    expect(
      within(dialog).getByText(new RegExp(t.control.decision.recorded)),
    ).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      within(explorer).queryAllByRole("button", {
        name: t.control.explorer.open,
      }).length,
    ).toBe(open.length - 1);
  });

  it("«Сначала» forgets every answer of the run and starts a new run", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await heading();
    await user.click(screen.getByRole("button", { name: t.control.sim.step }));
    await user.click(screen.getByRole("button", { name: t.control.nav.tasks }));
    const explorer = screen.getByRole("complementary", {
      name: t.control.explorer.title,
    });
    const open = await within(explorer).findAllByRole("button", {
      name: t.control.explorer.open,
    });
    await user.click(open[0]);
    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getAllByRole("button", { name: /^(Принять)$/ })[0],
    );
    await user.keyboard("{Escape}");
    const posted = fetchMock.mock.calls
      .map(
        ([url, init]) =>
          [String(url), init as RequestInit | undefined] as const,
      )
      .filter(
        ([url, init]) =>
          url.includes("/specialist-decisions") && init?.method === "POST",
      );
    expect(posted).toHaveLength(1);
    const body = JSON.parse(String(posted[0][1]?.body)) as { run_id: string };
    expect(body.run_id).toMatch(/^run-/);
    await user.click(screen.getByRole("button", { name: t.control.sim.reset }));
    expect(screen.getAllByText(t.control.sim.day(0)).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: t.control.nav.tasks }),
    ).not.toHaveTextContent(/[1-9]/);
    await user.click(screen.getByRole("button", { name: t.control.sim.step }));
    const again = await within(explorer).findAllByRole("button", {
      name: t.control.explorer.open,
    });
    expect(again.length).toBe(open.length);
    const runs = fetchMock.mock.calls
      .map(([url]) => new URL(String(url)).searchParams.get("run_id"))
      .filter((r): r is string => r !== null);
    expect(new Set(runs).size).toBeGreaterThanOrEqual(2);
  });

  it("clicking outside the dialog closes it", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await heading();
    const feed = screen.getByRole("region", { name: t.control.feed.title });
    await user.click(
      within(feed).getAllByRole("button", { name: t.control.feed.details })[0],
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeVisible();
    await user.click(
      document.querySelector(".decision-backdrop") as HTMLElement,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("the simulation survives navigation between pages", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await heading();
    await user.click(screen.getByRole("button", { name: t.control.sim.step }));
    await user.click(screen.getByRole("link", { name: t.control.nav.queue }));
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: t.control.pages.queueTitle,
      }),
    ).toBeVisible();
    expect(screen.getAllByRole("row").length).toBeGreaterThan(5);
    await user.click(screen.getByRole("link", { name: t.control.nav.tower }));
    await heading();
    expect(screen.getByText(t.control.sim.day(1))).toBeVisible();
  });

  it("the notifications page lists on the left and shows the whole subject on the right", async () => {
    const user = userEvent.setup();
    renderAt("/notifications");
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: t.control.pages.notificationsTitle,
      }),
    ).toBeVisible();
    const list = screen.getByRole("complementary", {
      name: t.control.alerts.title,
    });
    const rows = await within(list).findAllByRole("button");
    expect(rows.length).toBeGreaterThan(1);
    await user.click(rows[rows.length - 1]);
    const detail = screen.getByRole("region", {
      name: t.control.decision.title,
    });
    expect(within(detail).getByText(t.control.verdict.title)).toBeVisible();
    expect(within(detail).getByText(t.control.alerts.plainTitle)).toBeVisible();
  });

  it("switches to Kazakh and back without losing the page", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await heading();
    await user.click(screen.getByRole("button", { name: "KZ" }));
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Алдағы 14 күндегі ағын қысымы",
      }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Хабарламалар" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "RU" }));
    expect(await heading()).toBeVisible();
  });
});
