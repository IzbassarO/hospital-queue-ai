/**
 * Hospital mode: the picker, the three blocks, and the promises the screen makes about what it is showing.
 *
 * The load-bearing assertions are about honesty, not layout: nothing registered after the origin reaches the
 * queue, every measured-after-the-origin value is marked as hindsight, no model value is rendered anywhere, and a
 * thin queue says so instead of pretending to be a full one.
 */
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { t } from "../i18n";
import * as h from "./hospitalFixtures";
import { jsonResponse } from "./mockApi";
import { cleanupTower, prepareTower, renderAt } from "./towerHarness";
import { towerMock } from "./towerHarness";

const base = "/api/v1";
const DETAIL = /^\/waiting-list\/hospitals\/([^/]+)$/;
const REFERRALS = /^\/waiting-list\/hospitals\/([^/]+)\/referrals$/;

function hospitalMock() {
  const inner = towerMock();
  return (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(
      typeof input === "string" ? input : input.toString(),
      "http://localhost",
    );
    const path = url.pathname.replace(base, "");
    if (path === "/waiting-list/hospitals")
      return Promise.resolve(
        jsonResponse({
          items: h.hospitals,
          total: h.hospitals.length,
          limit: 500,
          offset: 0,
        }),
      );
    const detail = DETAIL.exec(path);
    if (detail)
      return Promise.resolve(
        detail[1] === h.THIN_ORG
          ? jsonResponse(h.thinDetail)
          : detail[1] === h.BIG_ORG
            ? jsonResponse(h.hospitalDetail)
            : jsonResponse({ detail: "unknown" }, 404),
      );
    const list = REFERRALS.exec(path);
    if (list) {
      const order = url.searchParams.get("order") ?? "longest_wait";
      const items = [...h.referrals].sort((a, b) =>
        order === "shortest_wait"
          ? a.days_waited_at_origin - b.days_waited_at_origin
          : b.days_waited_at_origin - a.days_waited_at_origin,
      );
      return Promise.resolve(
        jsonResponse({ items, total: items.length, limit: 25, offset: 0 }),
      );
    }
    return inner(input, init);
  };
}

beforeEach(() => {
  globalThis.fetch = hospitalMock() as typeof fetch;
  prepareTower();
});
afterEach(() => {
  cleanup();
  cleanupTower();
});

const bigName = h.hospitals[0].org_name;

describe("Hospital mode", () => {
  it("the picker lists hospitals with a real queue and hides the thin ones behind a choice", async () => {
    renderAt("/hospital");
    expect(
      await screen.findByRole("heading", { level: 1, name: t.hospital.title }),
    ).toBeVisible();
    expect(await screen.findByText(bigName)).toBeVisible();
    // SPARSE is out of the default list
    expect(screen.queryByText(h.hospitals[2].org_name)).toBeNull();

    await userEvent.click(
      screen.getByRole("checkbox", { name: t.hospital.pick.showSmall }),
    );
    const thin = await screen.findByText(h.hospitals[2].org_name);
    expect(thin).toBeVisible();
    // and it is labelled, not silently mixed in
    const row = thin.closest("a") as HTMLElement;
    expect(within(row).getByText(t.hospital.pick.smallTag)).toBeVisible();
  });

  it("search and the region filter narrow the list", async () => {
    renderAt("/hospital");
    await screen.findByText(bigName);
    await userEvent.type(
      screen.getByLabelText(t.hospital.pick.search),
      "городская",
    );
    await waitFor(() => expect(screen.queryByText(bigName)).toBeNull());
    expect(screen.getByText(h.hospitals[1].org_name)).toBeVisible();

    await userEvent.clear(screen.getByLabelText(t.hospital.pick.search));
    await userEvent.selectOptions(
      screen.getByLabelText(t.hospital.pick.region),
      "61",
    );
    await waitFor(() =>
      expect(screen.queryByText(h.hospitals[1].org_name)).toBeNull(),
    );
    expect(screen.getByText(bigName)).toBeVisible();
  });

  it("a deep link opens one hospital with its published totals", async () => {
    const router = renderAt(`/hospital/${h.BIG_ORG}`);
    expect(router.state.location.pathname).toBe(`/hospital/${h.BIG_ORG}`);
    expect(
      await screen.findByRole("heading", { level: 1, name: bigName }),
    ).toBeVisible();
    expect(screen.getByText(t.hospital.header.waiting)).toBeVisible();
    const waiting = screen.getByText(t.hospital.waiting.totals.waiting);
    expect(waiting.previousElementSibling?.textContent).toMatch(/240/);
  });

  it("the three blocks are present and named", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    await screen.findByRole("heading", { level: 1, name: bigName });
    for (const name of [
      t.hospital.forecast.title,
      t.hospital.waiting.title,
      t.hospital.replay.title,
    ]) {
      expect(await screen.findByRole("region", { name })).toBeVisible();
    }
  });

  it("no referral in the queue was registered after the origin, and none is a day hospital", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const block = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    const rows = within(block).getAllByRole("row").slice(1);
    expect(rows.length).toBe(h.referrals.length);
    for (const row of rows) {
      expect(within(row).queryByText("DH")).toBeNull();
      // registration date column is before the origin
      const cells = within(row).getAllByRole("cell");
      expect(cells[2].textContent).toMatch(/2025/);
    }
  });

  it("every measured-after-the-origin value is marked as hindsight", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const waiting = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    // the outcome column header carries the tag
    const outcomeHeader = within(waiting)
      .getAllByRole("columnheader")
      .find((c) => c.textContent?.includes(t.hospital.waiting.table.outcome));
    expect(outcomeHeader?.textContent).toContain(t.hospital.hindsight.tag);

    const replay = await screen.findByRole("region", {
      name: t.hospital.replay.title,
    });
    expect(
      within(replay).getAllByText(t.hospital.hindsight.tag).length,
    ).toBeGreaterThan(0);
    // the note names the origin date itself, not a generic disclaimer
    expect(replay.textContent).toContain(
      t.hospital.hindsight.note("17.03.2025"),
    );
  });

  it("the queue table shows no model value and no placeholder for one", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const waiting = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    const headers = within(waiting)
      .getAllByRole("columnheader")
      .map((c) => c.textContent ?? "");
    expect(headers).toHaveLength(5);
    for (const banned of [/риск/i, /прогноз ожид/i, /вероятн/i, /%/]) {
      expect(headers.join(" ")).not.toMatch(banned);
    }
    expect(waiting.textContent).toContain(
      t.hospital.waiting.table.noPredictions,
    );
  });

  it("the queue can be re-ordered by how long people have waited", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const waiting = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    const waited = () =>
      within(waiting)
        .getAllByRole("row")
        .slice(1)
        .map((r) => Number(within(r).getAllByRole("cell")[3].textContent));
    await waitFor(() => expect(waited()[0]).toBe(56));
    await userEvent.click(
      within(waiting).getByRole("button", {
        name: t.hospital.waiting.table.sortShortest,
      }),
    );
    await waitFor(() => expect(waited()[0]).toBe(21));
  });

  it("the replay reveals days only as the clock walks forward", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const replay = await screen.findByRole("region", {
      name: t.hospital.replay.title,
    });
    const revealed = () =>
      within(replay)
        .getAllByRole("row")
        .slice(1)
        .filter((r) => !r.className.includes("is-future")).length;
    expect(revealed()).toBe(0);
    await userEvent.click(
      within(replay).getByRole("button", { name: t.hospital.replay.step }),
    );
    await waitFor(() => expect(revealed()).toBe(1));
  });

  it("a thin queue warns instead of pretending", async () => {
    renderAt(`/hospital/${h.THIN_ORG}`);
    await screen.findByRole("heading", {
      level: 1,
      name: h.hospitals[2].org_name,
    });
    expect(screen.getByText(t.hospital.header.sparseWarning)).toBeVisible();
    expect(screen.getByText(t.hospital.header.support.SPARSE)).toBeVisible();
  });

  it("an unknown hospital says so and offers the way back", async () => {
    renderAt("/hospital/NOPE");
    expect(await screen.findByText(t.hospital.errors.unknown)).toBeVisible();
    expect(
      screen.getByRole("link", { name: t.hospital.errors.back }),
    ).toHaveAttribute("href", "/hospital");
  });

  it("the nav links to hospital mode", async () => {
    renderAt("/hospital");
    await screen.findByRole("heading", { level: 1, name: t.hospital.title });
    expect(
      screen.getByRole("link", { name: t.control.nav.hospital }),
    ).toHaveAttribute("href", "/hospital");
  });
});
