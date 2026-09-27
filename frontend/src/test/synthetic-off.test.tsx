/**
 * The control centre with the synthetic layer switched off (VITE_SYNTHETIC=off): published signals only. The map,
 * the notifications and the specialist's decisions work; the queue and the day simulation are absent and say so;
 * nothing crashes, no NaN, no console errors.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { t } from "../i18n";
import { SYNTHETIC_ENABLED } from "../tower/synthetic";
import {
  cleanupTower,
  FORBIDDEN,
  MACHINE_WORD,
  prepareTower,
  primaryText,
  renderAt,
  towerMock,
} from "./towerHarness";

vi.hoisted(() => vi.stubEnv("VITE_SYNTHETIC", "off"));

let fetchMock: ReturnType<typeof towerMock>;
let consoleError: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  fetchMock = towerMock();
  prepareTower();
  consoleError = vi.spyOn(console, "error");
});
afterEach(cleanupTower);

const heading = () =>
  screen.findByRole("heading", { level: 1, name: t.control.title });
const noData = () => t.common.noData;

describe("Control centre with the synthetic layer off", () => {
  it("the flag reads the environment", () => {
    expect(SYNTHETIC_ENABLED).toBe(false);
  });

  it("/ shows the published origin: map, notifications, no simulation, no queue counts", async () => {
    renderAt("/");
    expect(await heading()).toBeVisible();
    expect(
      screen.getByRole("img", { name: t.control.map.title }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: t.control.sim.play }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: t.control.sim.step }),
    ).not.toBeInTheDocument();
    const note = screen.getByRole("status", {
      name: t.control.syntheticOff.title,
    });
    expect(note).toBeVisible();
    const waiting = document.querySelector("dl.waiting") as HTMLElement;
    const values = within(waiting)
      .getAllByRole("definition")
      .map((el) => el.textContent);
    expect(values.slice(0, 3)).toEqual([noData(), noData(), noData()]);
    expect(values[3]).toBe("0");
    expect(screen.getByText(t.control.syntheticOff.waiting)).toBeVisible();
    const feed = screen.getByRole("region", { name: t.control.feed.title });
    expect(within(feed).getByText(t.control.syntheticOff.feed)).toBeVisible();
    expect(
      within(feed).getAllByText("Костанайская областная больница").length,
    ).toBeGreaterThan(0);
    expect(within(feed).getAllByText(t.control.publishedTag).length).toBe(1);
    expect(
      screen.getByRole("button", { name: t.control.nav.tasks }),
    ).not.toHaveTextContent(/[1-9]/);
    expect(document.body.textContent).not.toMatch(/NaN|undefined/);
    for (const pattern of FORBIDDEN) expect(primaryText()).not.toMatch(pattern);
    expect(primaryText()).not.toMatch(MACHINE_WORD);
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("/queue is an explicit empty state with the decision journal", async () => {
    renderAt("/queue");
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: t.control.pages.queueTitle,
      }),
    ).toBeVisible();
    const queue = screen.getByRole("status", { name: t.control.queue.title });
    expect(within(queue).getByText(t.control.syntheticOff.queue)).toBeVisible();
    expect(screen.queryAllByRole("row")).toHaveLength(0);
    expect(
      screen.queryByRole("button", { name: t.control.exportCsv.queue }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: t.control.decision.logTitle }),
    ).toBeVisible();
    expect(screen.getByText(t.control.decision.logEmpty)).toBeVisible();
    expect(document.body.textContent).not.toMatch(/NaN|undefined/);
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("/notifications lists the published notifications and records a decision", async () => {
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
    await user.click(
      within(detail).getByRole("button", {
        name: t.control.decision.actions.accept.label,
      }),
    );
    // the decision is shown as recorded only after the server round trip resolves
    expect(
      await within(detail).findByText(new RegExp(t.control.decision.recorded)),
    ).toBeVisible();
    const posted = fetchMock.mock.calls.filter(
      ([url, init]) =>
        String(url).includes("/specialist-decisions") &&
        (init as RequestInit | undefined)?.method === "POST",
    );
    expect(posted).toHaveLength(1);
    expect(consoleError).not.toHaveBeenCalled();
  });
});
