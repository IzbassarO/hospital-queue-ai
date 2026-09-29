/** Control centre behaviour: real published inputs, the day unfolding, the specialist's tasks, two languages. */
import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { t } from "../i18n";
import { fmtNumber } from "../lib/format";
import { resetRegionFilter } from "../tower/region";
import * as d from "./demoFixtures";
import {
  cleanupTower,
  FORBIDDEN,
  MACHINE_WORD,
  prepareTower,
  primaryText,
  renderAt,
  towerMock,
} from "./towerHarness";

let fetchMock: ReturnType<typeof towerMock>;
beforeEach(() => {
  fetchMock = towerMock();
  prepareTower();
  resetRegionFilter();
});
afterEach(cleanupTower);

/** Digit groups are rendered with a non-breaking space; compare the readable form. */
const plain = (value: string | null) => (value ?? "").replace(/\s+/g, " ");

/** The number printed above one counter label (the <dd> of its <dt>). */
const counterValue = (label: string): string =>
  screen.getByText(label).previousElementSibling?.textContent ?? "";

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

  it("the lede and the funnel counters are siblings, so they can sit side by side above the map", async () => {
    renderAt("/");
    await heading();
    const lead = document.querySelector("section.tower-lead") as HTMLElement;
    expect(lead).toBeVisible();
    // The text block and the counters must stay direct children of .tower-lead: the two-column layout that keeps
    // the map above the fold is a grid on that element, and a wrapper around either one would collapse it.
    const children = [...lead.children].map((node) => node.className);
    expect(children).toEqual(["tower-lead-text", "count-chain"]);
    const text = lead.querySelector(".tower-lead-text") as HTMLElement;
    expect(text.querySelector("h1")).toBeVisible();
    expect(text.querySelector("p")).toBeVisible();
    // Four counters, each a number above its label, still readable as the published → attention → high funnel.
    const chain = lead.querySelector("dl.count-chain") as HTMLElement;
    expect(within(chain).getAllByRole("definition")).toHaveLength(4);
    expect(counterValue(t.control.chain.published)).not.toBe("");
    expect(counterValue(t.control.chain.attention)).not.toBe("");
    expect(counterValue(t.control.chain.high)).not.toBe("");
    expect(counterValue(t.control.chain.lowVolume)).not.toBe("");
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
    // the decision is shown as recorded only after the server round trip resolves
    expect(
      await within(dialog).findByText(new RegExp(t.control.decision.recorded)),
    ).toBeVisible();
    // ... with its transparency-ledger receipt: entry number, shortened hash, and a link to check it
    const receipt = within(dialog).getByTestId("decision-receipt");
    expect(receipt).toHaveTextContent(t.verify.receipt.entry(1427));
    expect(within(receipt).getByTitle(/^83ab5f0c/)).toHaveTextContent(
      "83ab5f0c…f90a12f9",
    );
    expect(
      within(receipt).getByRole("link", { name: t.verify.receipt.verify }),
    ).toHaveAttribute("href", "/verify?seq=1427");
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

/**
 * Honesty of what the screen claims, and usefulness of what it lists: the crossing is checked against the real
 * observed day where the mart has one, the interval names its measured coverage next to the nominal one, the
 * published facts of the mart sit apart from the synthetic queue, and the inbox can be read the way a bureau
 * specialist reads it.
 */
describe("Control centre: facts, coverage and the bureau's own view", () => {
  it("the fact of the mart sits beside the synthetic waiting counters, labelled and sourced", async () => {
    renderAt("/");
    await heading();
    const facts = screen.getByRole("region", { name: t.control.facts.title });
    expect(facts).toBeVisible();
    // the national row of the mart fixture: 89 545 waiting, median 8 days, refusals 9,5 %
    const text = plain(facts.textContent);
    expect(text).toContain(plain(fmtNumber(89545, 0)));
    expect(text).toContain(plain(t.control.queue.days(8)));
    expect(text).toContain("9,5 %");
    expect(within(facts).getByText(t.control.publishedTag)).toBeVisible();
    expect(within(facts).getByText(t.control.facts.note)).toBeVisible();
    // the synthetic counters keep their own tag, so the two blocks cannot be read as one number
    const waiting = document.querySelector(".waiting-block") as HTMLElement;
    expect(
      within(waiting).getAllByText(t.control.syntheticTag).length,
    ).toBeGreaterThan(3);
  });

  it("a crossing the mart can answer is confirmed by the fact, not by a synthesised flow", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await heading();
    await user.click(screen.getByRole("button", { name: t.control.sim.step }));
    await user.click(screen.getByRole("button", { name: t.control.sim.step }));
    const feed = screen.getByRole("region", { name: t.control.feed.title });
    expect(
      within(feed).getByText(
        t.control.sim.events.confirmed(
          "Костанайская областная больница",
          "4,0",
          "1,0",
          "fact",
        ),
      ),
    ).toBeVisible();
    expect(counterValue(t.control.sim.counters.confirmedFact)).toBe("1");
    expect(counterValue(t.control.sim.counters.confirmedSynthetic)).toBe("0");
  });

  it("the subject shows the measured coverage next to the nominal one and names the source of the observed value", async () => {
    const user = userEvent.setup();
    renderAt("/notifications");
    await screen.findByRole("heading", {
      level: 1,
      name: t.control.pages.notificationsTitle,
    });
    const detail = screen.getByRole("region", {
      name: t.control.decision.title,
    });
    expect(
      within(detail).getByText(
        t.control.alerts.facts.coverageHint("80%", "70%"),
      ),
    ).toBeVisible();
    // the historical facts of the card reach the subject too
    expect(
      within(detail).getByText(t.control.alerts.facts.backlog),
    ).toBeVisible();
    await user.click(screen.getByRole("link", { name: t.control.nav.tower }));
    await heading();
    await user.click(screen.getByRole("button", { name: t.control.sim.step }));
    await user.click(screen.getByRole("button", { name: t.control.sim.step }));
    await user.click(
      screen.getByRole("link", { name: t.control.nav.notifications }),
    );
    const list = await screen.findByRole("complementary", {
      name: t.control.alerts.title,
    });
    await user.click(within(list).getByText("Костанайская областная больница"));
    const inbox = screen.getByRole("region", {
      name: t.control.decision.title,
    });
    expect(
      within(inbox).getByText(t.control.alerts.facts.observedFact),
    ).toBeVisible();
    expect(
      within(inbox).queryByText(t.control.alerts.facts.observedSynthetic),
    ).not.toBeInTheDocument();
  });

  it("the inbox keeps day-hospital series out of the default view and says how many they are", async () => {
    cleanupTower();
    fetchMock = towerMock([d.dayHospitalSignal]);
    prepareTower();
    resetRegionFilter();
    const user = userEvent.setup();
    renderAt("/notifications");
    await screen.findByRole("heading", {
      level: 1,
      name: t.control.pages.notificationsTitle,
    });
    const list = screen.getByRole("complementary", {
      name: t.control.alerts.title,
    });
    const chip = (label: string) =>
      within(list).getByRole("button", { name: new RegExp(`^${label}`) });
    expect(chip(t.control.facet.withoutDayHospital)).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(chip(t.control.facet.dayHospitalOnly)).toHaveTextContent(/1$/);
    const dayHospitalRows = () =>
      [...list.querySelectorAll("ol.inbox-rows .inbox-row-meta")].filter((el) =>
        (el.textContent ?? "").includes("Дневной стационар"),
      );
    const rowCount = () => list.querySelectorAll("ol.inbox-rows li").length;
    expect(dayHospitalRows()).toHaveLength(0);
    const withoutDh = rowCount();
    await user.click(chip(t.control.facet.dayHospitalOnly));
    expect(dayHospitalRows()).toHaveLength(1);
    expect(rowCount()).toBe(1);
    await user.click(chip(t.control.facet.allProfiles));
    expect(dayHospitalRows()).toHaveLength(1);
    expect(rowCount()).toBe(withoutDh + 1);
  });

  it("the order chips re-read the same rows by queue and by historical wait", async () => {
    const user = userEvent.setup();
    renderAt("/notifications");
    await screen.findByRole("heading", {
      level: 1,
      name: t.control.pages.notificationsTitle,
    });
    const list = screen.getByRole("complementary", {
      name: t.control.alerts.title,
    });
    const titles = () =>
      within(list)
        .getAllByRole("button")
        .map((el) => el.querySelector(".inbox-row-title")?.textContent)
        .filter((v): v is string => Boolean(v));
    expect(titles()[0]).toBe("Костанайская областная больница");
    await user.click(
      within(list).getByRole("button", { name: t.control.facet.byQueue }),
    );
    // 22VJ carries the largest queue of the mart fixture (214), 000V 97, ZH60 18
    expect(titles()[0]).toBe("Костанайский областной кардиологический центр");
    await user.click(
      within(list).getByRole("button", { name: t.control.facet.byWait }),
    );
    expect(titles()[0]).toBe("Костанайская областная больница");
  });

  it("the longest queues of the mart are a separate descriptive list, never a model warning", async () => {
    renderAt("/notifications");
    await screen.findByRole("heading", {
      level: 1,
      name: t.control.pages.notificationsTitle,
    });
    const block = await screen.findByRole("region", {
      name: t.control.queueFacts.title,
    });
    expect(within(block).getByText(t.control.queueFacts.tag)).toBeVisible();
    expect(within(block).getByText(fmtNumber(719, 0))).toBeVisible();
    expect(
      within(block).getByText("Городская клиническая больница № 1"),
    ).toBeVisible();
    // it lives outside the inbox list, so a queue row is never read as a published signal
    const list = screen.getByRole("complementary", {
      name: t.control.alerts.title,
    });
    expect(list.contains(block)).toBe(false);
    for (const pattern of FORBIDDEN) expect(primaryText()).not.toMatch(pattern);
  });

  it("no patient-level clinical wording and no promise the system acts, in both languages", async () => {
    const user = userEvent.setup();
    renderAt("/");
    await heading();
    await user.click(screen.getByRole("button", { name: t.control.sim.step }));
    const claims = [/без риска/i, /сдвигается/i, /получит запрос/i];
    const read = () => document.body.textContent ?? "";
    for (const pattern of claims) expect(read()).not.toMatch(pattern);
    await user.click(screen.getByRole("button", { name: "KZ" }));
    await screen.findByRole("heading", {
      level: 1,
      name: "Алдағы 14 күндегі ағын қысымы",
    });
    for (const pattern of [...claims, /қауіпсіз/i]) {
      expect(read()).not.toMatch(pattern);
    }
    for (const pattern of FORBIDDEN) expect(primaryText()).not.toMatch(pattern);
  });

  it("the queue download names itself synthetic in the file name, a comment line and every row", async () => {
    const user = userEvent.setup();
    const blobs: Blob[] = [];
    const names: string[] = [];
    const createObjectURL = URL.createObjectURL;
    const revokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = (blob: Blob) => {
      blobs.push(blob);
      return "blob:queue";
    };
    URL.revokeObjectURL = () => undefined;
    const click = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () {
      names.push(this.download);
    };
    try {
      renderAt("/queue");
      await screen.findByRole("heading", {
        level: 1,
        name: t.control.pages.queueTitle,
      });
      await user.click(
        screen.getByRole("button", { name: t.control.exportCsv.queue }),
      );
      expect(names[0]).toBe("synthetic-queue-2025-03-17.csv");
      const csv = await blobs[0].text();
      expect(csv).toContain(
        `# ${t.control.exportCsv.syntheticNote("17.03.2025")}`,
      );
      const rows = csv.split("\n");
      const header = rows.find((r) =>
        r.startsWith(t.control.queue.columns.id),
      ) as string;
      expect(header.endsWith(t.control.exportCsv.sourceColumn)).toBe(true);
      const body = rows.slice(rows.indexOf(header) + 1).filter(Boolean);
      expect(body.length).toBeGreaterThan(0);
      for (const row of body)
        expect(row.endsWith(t.control.exportCsv.sourceSynthetic)).toBe(true);
    } finally {
      HTMLAnchorElement.prototype.click = click;
      URL.createObjectURL = createObjectURL;
      URL.revokeObjectURL = revokeObjectURL;
    }
  });
});
