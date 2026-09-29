/**
 * Shared scaffolding of the control-centre tests: the API mock of one published origin, a router render at a path,
 * the primary-text reader with the vocabulary it must never contain, and the environment every test starts from.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";
import { setLang } from "../i18n";
import { routes } from "../routes";
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
const CARD = /^\/hospitals\/([^/]+)\/profiles\/([^/]+)$/;

/** `extra` adds published signals to the origin, for tests about the facets rather than about the default list. */
export function towerMock(extra: typeof ALL = []) {
  const signals = [...ALL, ...extra];
  return operationalMock((url) => {
    const path = url.pathname.replace(base, "");
    if (path === "/dictionaries") return jsonResponse(d.demoDictionaries);
    if (path === "/overview") return jsonResponse(fixtures.overview);
    if (path === "/alerts")
      return jsonResponse({
        items: d.loadAlerts,
        total: d.loadAlerts.length,
        limit: 500,
        offset: 0,
      });
    const card = CARD.exec(path);
    if (card) return jsonResponse(d.towerCard(card[1], card[2]));
    if (path === "/operational-intelligence/overview")
      return jsonResponse(d.demoOverview);
    if (path === "/operational-intelligence/signals") {
      const severity = url.searchParams.get("severity");
      const items = signals.filter((s) => !severity || s.severity === severity);
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
          run_id: "test-run",
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
          publication_identity_sha256: null,
          receipt: {
            ledger_seq: 1427,
            entry_hash:
              "83ab5f0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f60718293a4b5c6d7e8f90a12f9",
            event_type: "decision.recorded",
            subject: "specialist_decision:1",
            created_at: "2026-09-23T21:00:00.000000Z",
            verify_path: "/verify?seq=1427",
          },
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

export function renderAt(path: string) {
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

/** Text of <main> without the technical and non-claim blocks: what a reader takes as the product's own words. */
export function primaryText(): string {
  const main = document.querySelector("main");
  const clone = main?.cloneNode(true) as HTMLElement | undefined;
  clone
    ?.querySelectorAll("[data-technical], [data-nonclaim], svg title")
    .forEach((el) => el.remove());
  return clone?.textContent ?? "";
}

export const FORBIDDEN = [
  /рекоменд/i,
  /маршрутиз/i,
  /оптимиз/i,
  /свободн\S* кой/i,
  /цифров\S* двойник/i,
];
export const MACHINE_WORD = /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b/;

/** A fresh store, nothing remembered from a previous test, Russian, and the jsdom stubs the pages need. */
export function prepareTower() {
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
}

export function cleanupTower() {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.getElementById("root")?.remove();
}
