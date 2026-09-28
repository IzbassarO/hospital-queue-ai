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
import { setLang, t } from "../i18n";
import { fmtNumber, fmtPercent } from "../lib/format";
import * as h from "./hospitalFixtures";
import { jsonResponse } from "./mockApi";
import { cleanupTower, prepareTower, renderAt } from "./towerHarness";
import { towerMock } from "./towerHarness";

const base = "/api/v1";
const DETAIL = /^\/waiting-list\/hospitals\/([^/]+)$/;
const REFERRALS = /^\/referral-estimates\/hospitals\/([^/]+)\/referrals$/;
const PUBLICATION = "/referral-estimates/publication";
const WORKLIST_PUBLICATION = "/verification-worklist/publication";
const WORKLIST_REGIONS = "/verification-worklist/regions";
const WORKLIST_HOSPITAL = /^\/verification-worklist\/hospitals\/([^/]+)$/;

/**
 * `estimates: false` is the product before the estimate publication exists — the queue still answers and the
 * model columns are simply absent. Both states are real, so both are tested.
 */
function hospitalMock({
  estimates = true,
  worklist = true,
}: { estimates?: boolean; worklist?: boolean } = {}) {
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
    if (path === PUBLICATION)
      return Promise.resolve(
        estimates
          ? jsonResponse(h.estimatesPublication)
          : jsonResponse({ detail: "no publication" }, 404),
      );
    if (path === WORKLIST_PUBLICATION)
      return Promise.resolve(
        worklist
          ? jsonResponse(h.worklistPublication)
          : jsonResponse({ detail: "no publication" }, 404),
      );
    if (path === WORKLIST_REGIONS)
      return Promise.resolve(jsonResponse(h.worklistRegions));
    const hospitalWorklist = WORKLIST_HOSPITAL.exec(path);
    if (hospitalWorklist) {
      const limited = url.searchParams.get("history_quality_warning");
      const order = url.searchParams.get("order") ?? "rank";
      let items = [...h.worklistItems];
      if (limited === "true")
        items = items.filter((i) => i.history_quality_warning);
      items.sort((a, b) =>
        order === "longest_wait"
          ? b.days_waited_at_origin - a.days_waited_at_origin
          : a.rank - b.rank,
      );
      return Promise.resolve(
        jsonResponse({ ...h.worklistHospital, items, total: items.length }),
      );
    }
    const list = REFERRALS.exec(path);
    if (list) {
      const order = url.searchParams.get("order") ?? "longest_wait";
      const attention = url.searchParams.get("attention") === "true";
      const source = estimates
        ? h.queueReferrals
        : h.queueReferrals.map((row) => ({ ...row, estimate: null }));
      const items = source
        .filter((row) => !attention || row.estimate?.refusal_attention)
        .sort((a, b) => {
          if (order === "highest_refusal_risk")
            return (
              (b.estimate?.refused_30d ?? -1) - (a.estimate?.refused_30d ?? -1)
            );
          return order === "shortest_wait"
            ? a.days_waited_at_origin - b.days_waited_at_origin
            : b.days_waited_at_origin - a.days_waited_at_origin;
        });
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

  it("the four blocks are present and named", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    await screen.findByRole("heading", { level: 1, name: bigName });
    for (const name of [
      t.hospital.forecast.title,
      t.hospital.waiting.title,
      t.hospital.why.title,
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

  it("without an estimate publication the queue table shows no model value and no placeholder for one", async () => {
    globalThis.fetch = hospitalMock({ estimates: false }) as typeof fetch;
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
    // and nothing else on the screen claims a model estimate either
    expect(
      screen.queryByRole("region", { name: t.hospital.why.title }),
    ).toBeNull();
    expect(screen.queryByText(t.hospital.calibration.title)).toBeNull();
  });

  it("the published estimates appear as columns of the same queue table, each row with its evidence tier", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const waiting = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    await waitFor(() =>
      expect(within(waiting).getAllByRole("row").length).toBeGreaterThan(1),
    );
    const headers = within(waiting)
      .getAllByRole("columnheader")
      .map((c) => c.textContent ?? "");
    expect(headers).toHaveLength(9);
    expect(headers.join(" ")).toContain(t.hospital.estimates.columns.admitted);
    expect(headers.join(" ")).toContain(t.hospital.estimates.columns.window);

    const first = within(waiting).getAllByRole("row")[1];
    const cells = within(first).getAllByRole("cell");
    // the longest-waiting referral is #1: 62% by day 14, hospital-level evidence
    expect(cells[4].textContent).toContain("62");
    expect(cells[7].textContent).toContain(
      t.hospital.estimates.tier.hospital_profile,
    );
    // the model's abstention is a sentence, never an empty cell
    const abstaining = within(waiting)
      .getAllByRole("row")
      .find((r) => r.textContent?.includes(t.hospital.estimates.tier.profile));
    expect(abstaining?.textContent).toContain(
      t.hospital.estimates.window.abstainShort,
    );
  });

  it("a collapsed 30-day estimate says so instead of printing a confident 0%", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const waiting = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    await waitFor(() =>
      expect(within(waiting).getAllByRole("row").length).toBeGreaterThan(1),
    );
    // referral 3 puts its whole 30-day mass on "still waiting": the row must not read as a certainty
    const degenerate = within(waiting)
      .getAllByRole("row")
      .find((r) => r.textContent?.includes(t.hospital.estimates.tier.profile));
    expect(degenerate?.textContent).toContain(
      t.hospital.estimates.degenerate.short,
    );
    // and the hint a reader hovers is the published definition, not a phrase invented in the UI
    const note = within(degenerate as HTMLElement).getAllByText(
      t.hospital.estimates.degenerate.short,
    )[0];
    expect(note.getAttribute("title")).toBe(
      h.estimatesPublication.degeneracy.definition,
    );
    // a well-supported row keeps its ordinary sub-line
    const supported = within(waiting)
      .getAllByRole("row")
      .find((r) =>
        r.textContent?.includes(t.hospital.estimates.tier.hospital_profile),
      );
    expect(supported?.textContent).not.toContain(
      t.hospital.estimates.degenerate.short,
    );
  });

  it("the model panel publishes how many rows collapsed, with the reason", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const why = await screen.findByRole("region", {
      name: t.hospital.why.title,
    });
    expect(why.textContent).toContain(
      t.hospital.estimates.degenerate.count(
        fmtNumber(h.estimatesPublication.degeneracy.count, 0),
        fmtNumber(h.estimatesPublication.referral_count, 0),
      ),
    );
    expect(why.textContent).toContain(
      h.estimatesPublication.degeneracy.definition,
    );
  });

  it("the refusal-risk order is offered as administrative follow-up, in those words", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const waiting = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    await userEvent.click(
      within(waiting).getByRole("button", {
        name: t.hospital.estimates.attention.sort,
      }),
    );
    const risks = () =>
      within(waiting)
        .getAllByRole("row")
        .slice(1)
        .map((r) => within(r).getAllByRole("cell")[5].textContent ?? "");
    await waitFor(() => expect(risks()[0]).toContain("34"));
    // the note says what the threshold is and what the user is expected to do with it
    expect(waiting.textContent).toContain(t.hospital.estimates.attention.use);
    expect(waiting.textContent).toContain(
      t.hospital.estimates.attention.rule("22%"),
    );
    // no medical wording anywhere near the control
    for (const banned of [/тяжест/i, /диагноз/i, /показан/i, /срочност/i]) {
      expect(waiting.textContent ?? "").not.toMatch(banned);
    }
  });

  it("the attention filter keeps only the flagged referrals", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const waiting = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    await waitFor(() =>
      expect(within(waiting).getAllByRole("row").length).toBe(
        h.queueReferrals.length + 1,
      ),
    );
    await userEvent.click(
      within(waiting).getByRole("checkbox", {
        name: t.hospital.estimates.attention.filter,
      }),
    );
    await waitFor(() =>
      expect(within(waiting).getAllByRole("row").length).toBe(2),
    );
  });

  it("the model panel reads the tournament from the publication, fallback and all", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const why = await screen.findByRole("region", {
      name: t.hospital.why.title,
    });
    for (const row of h.estimatesPublication.selection.candidates) {
      expect(
        within(why).getByText(t.hospital.why.models[row.model_key]),
      ).toBeVisible();
    }
    // the numbers are the published ones, not a rounding of something else
    expect(why.textContent).toContain("0,0979");
    expect(why.textContent).toContain("0,1260");
    expect(why.textContent).toContain(
      h.estimatesPublication.selection.decision_rule,
    );
    expect(within(why).getByText(t.hospital.why.fallbackNote)).toBeVisible();
    expect(
      within(why).getAllByText(t.hospital.why.verdict.rejected).length,
    ).toBe(2);
  });

  it("the calibration view lives inside the hindsight block and is labelled as hindsight", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const replay = await screen.findByRole("region", {
      name: t.hospital.replay.title,
    });
    const heading = within(replay).getByRole("heading", {
      name: new RegExp(t.hospital.calibration.title),
    });
    expect(heading.textContent).toContain(t.hospital.hindsight.tag);
    // weighted over the published bins: promised 41.2%, observed 31.8%
    expect(replay.textContent).toContain(
      t.hospital.calibration.summary("41,2%", "31,8%"),
    );
    expect(replay.textContent).toContain(t.hospital.calibration.verdict.over);
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

  it("the verification worklist is a second tab, not a second queue", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const section = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    const tab = within(section).getByRole("tab", {
      name: t.hospital.tabs.worklist,
    });
    // the measured queue is what the screen opens on
    expect(
      within(section).getByRole("tab", { name: t.hospital.tabs.queue }),
    ).toHaveAttribute("aria-selected", "true");
    await userEvent.click(tab);
    await waitFor(() => expect(tab).toHaveAttribute("aria-selected", "true"));
    // and the two never share the screen, so nobody can subtract one from the other
    expect(
      within(section).getByRole("heading", { name: t.hospital.worklist.title }),
    ).toBeVisible();
    const panel = document.querySelector("#hos-panel-queue") as HTMLElement;
    expect(panel.hidden).toBe(true);
  });

  it("the worklist ranks the whole formal queue, subtracts nothing and says who decides", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const section = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    await userEvent.click(
      within(section).getByRole("tab", { name: t.hospital.tabs.worklist }),
    );
    await screen.findByRole("heading", { name: t.hospital.worklist.title });
    expect(section.textContent).toContain(t.hospital.worklist.notAQueue("240"));
    // the publication's own sentence, not a phrase invented in the UI, and it appears above the list
    const notes = within(section).getAllByText(h.NOT_A_DECISION.ru);
    expect(notes.length).toBeGreaterThan(0);
    expect(section.textContent).toContain(
      h.worklistPublication.ranking.definition.ru,
    );
    // the earlier binary rule is shown as a reference, never as the selector
    expect(section.textContent).toContain(
      h.worklistPublication.legacy_rule.statement.ru,
    );
  });

  it("the worklist never uses removal or ghost wording, in either language", async () => {
    for (const lang of ["ru", "kk"] as const) {
      setLang(lang);
      cleanup();
      renderAt(`/hospital/${h.BIG_ORG}`);
      const section = await screen.findByRole("region", {
        name: t.hospital.waiting.title,
      });
      await userEvent.click(
        within(section).getByRole("tab", { name: t.hospital.tabs.worklist }),
      );
      await screen.findByRole("heading", { name: t.hospital.worklist.title });
      const text = (section.textContent ?? "").toLowerCase();
      for (const banned of [
        "призрак",
        "фиктив",
        "удалить",
        "удаления",
        "снять с очереди",
        "жалған",
        "жою",
        "фейк",
      ]) {
        expect(text).not.toContain(banned);
      }
      // and it says the two things it must, in the language the reader is reading
      expect(text).toContain(t.hospital.worklist.history.tag.toLowerCase());
      expect(text).toContain(t.hospital.worklist.table.priority.toLowerCase());
      expect(text).toContain(h.NOT_A_DECISION[lang].toLowerCase());
    }
    setLang("ru");
  });

  it("a row resting on little comparable history says so, and can be filtered to", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const section = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    await userEvent.click(
      within(section).getByRole("tab", { name: t.hospital.tabs.worklist }),
    );
    const table = await screen.findByRole("table", {
      name: t.hospital.worklist.table.title,
    });
    await waitFor(() =>
      expect(within(table).getAllByRole("row").length).toBe(
        h.worklistItems.length + 1,
      ),
    );
    const marks = within(table).getAllByText(t.hospital.worklist.history.tag);
    const warned = h.worklistItems.filter((i) => i.history_quality_warning);
    expect(marks.length).toBe(warned.length);
    // the source's own reason, then what the mark means
    expect(marks[0].getAttribute("title")).toBe(
      `${t.hospital.worklist.history.reasons.degenerate_conditional_distribution}. ${h.worklistPublication.history_quality.definition.ru}`,
    );
    await userEvent.click(
      within(section).getByRole("checkbox", {
        name: t.hospital.worklist.history.all,
      }),
    );
    await waitFor(() =>
      expect(within(table).getAllByRole("row").length).toBe(warned.length + 1),
    );
  });

  it("the yield curve is read from the publication and labelled as hindsight", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const section = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    await userEvent.click(
      within(section).getByRole("tab", { name: t.hospital.tabs.worklist }),
    );
    const heading = await screen.findByRole("heading", {
      name: new RegExp(t.hospital.worklist.yieldTitle),
    });
    expect(heading.textContent).toContain(t.hospital.hindsight.tag);
    // the published base and best point, not numbers computed in the UI
    const curve = h.worklistPublication.yield_curve;
    const best = curve.points[3];
    expect(section.textContent).toContain(
      t.hospital.worklist.yieldLead(
        fmtPercent(curve.base.share, 1),
        fmtNumber(best.checked, 0),
        fmtPercent(best.share, 1),
        fmtNumber(best.lift, 2),
      ),
    );
    // every canonical point is on screen with its lift, and the base row closes the table
    const table = within(section).getByRole("table", {
      name: t.hospital.worklist.yieldTitle,
    });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(curve.points.length + 2);
    expect(rows[2].textContent).toContain(`${fmtNumber(0.983314, 2)}×`);
    expect(rows[rows.length - 1].textContent).toContain(
      t.hospital.worklist.yieldBase,
    );
    // a top-1000 point below the base means the panel says the order helps only modestly
    expect(section.textContent).toContain(t.hospital.worklist.yieldWeak);
  });

  it("the region view shows this hospital's region with its formal queue beside the count", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const section = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    await userEvent.click(
      within(section).getByRole("tab", { name: t.hospital.tabs.worklist }),
    );
    const table = await screen.findByRole("table", {
      name: t.hospital.worklist.regionTitle,
    });
    const own = within(table).getAllByRole("row")[1];
    expect(own.textContent).toContain(h.worklistRegions[0].name);
    expect(own.textContent).toContain(fmtNumber(2381, 0));
    expect(own.textContent).toContain(fmtNumber(7960, 0));
    // other regions are one click away, not hidden
    await userEvent.click(
      within(section).getByRole("button", {
        name: t.hospital.worklist.showAllRegions,
      }),
    );
    await waitFor(() =>
      expect(within(table).getAllByRole("row").length).toBe(
        h.worklistRegions.length + 1,
      ),
    );
  });

  it("without a worklist publication the hospital screen has no second tab", async () => {
    globalThis.fetch = hospitalMock({ worklist: false }) as typeof fetch;
    renderAt(`/hospital/${h.BIG_ORG}`);
    const section = await screen.findByRole("region", {
      name: t.hospital.waiting.title,
    });
    await within(section).findByRole("table", {
      name: t.hospital.waiting.table.title,
    });
    expect(within(section).queryAllByRole("tab")).toHaveLength(0);
    expect(screen.queryByText(t.hospital.worklist.title)).toBeNull();
  });

  it("the replay reveals days only as the clock walks forward", async () => {
    renderAt(`/hospital/${h.BIG_ORG}`);
    const replay = await screen.findByRole("region", {
      name: t.hospital.replay.title,
    });
    const table = within(replay).getByRole("table", {
      name: t.hospital.replay.title,
    });
    const revealed = () =>
      within(table)
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
