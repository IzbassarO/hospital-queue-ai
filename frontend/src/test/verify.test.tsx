/**
 * "Проверяемый ИИ" (/verify) and the decision receipt. The load-bearing assertions: the browser reaches its own verdict
 * from the export (a tampered export is BROKEN even when the server says OK), a trusted head recorded earlier is
 * checked, both languages are complete, hashes copy in full, and nothing private is ever rendered.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLang, t } from "../i18n";
import { kk } from "../i18n/kk";
import { ru } from "../i18n/ru";
import { canonicalText } from "../verify/canonical";
import { jsonResponse } from "./mockApi";
import {
  cleanupTower,
  prepareTower,
  renderAt,
  towerMock,
} from "./towerHarness";

interface Entry {
  seq: number;
  created_at: string;
  event_type: string;
  subject: string;
  payload: Record<string, unknown>;
  prev_hash: string;
  entry_hash: string;
}
const vectors = JSON.parse(
  readFileSync(
    resolve(process.cwd(), "../docs/transparency-ledger-vectors.json"),
    "utf8",
  ),
) as { chain: Entry[] };
const chain = vectors.chain;
const head = chain[chain.length - 1];
const exportOf = (entries: Entry[]) =>
  entries.map((e) => `${canonicalText(e)}\n`).join("");

const serverOk = {
  status: "OK",
  mode: "server",
  verified_at: "2026-09-28T15:20:11.402Z",
  duration_ms: 12,
  chain_length: chain.length,
  verified_through_seq: head.seq,
  head_seq: head.seq,
  head_hash: head.entry_hash,
  failure_seq: null,
  reason_code: null,
  subject: null,
  issues: [],
  covered_decisions: 2,
  covered_publications: 1,
  checks: ["chain"],
};
const serverBroken = {
  ...serverOk,
  status: "BROKEN",
  verified_through_seq: 3,
  failure_seq: 4,
  reason_code: "COMMITMENT_MISMATCH",
  subject: "specialist_decision:41",
  issues: [
    {
      seq: 4,
      reason_code: "COMMITMENT_MISMATCH",
      subject: "specialist_decision:41",
      detail: "current value of comment does not match the committed value",
    },
  ],
};

function mockLedger({
  server = serverOk,
  exported = exportOf(chain),
}: { server?: object; exported?: string } = {}) {
  const inner = towerMock();
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const path = url.pathname.replace("/api/v1", "");
    if (path === "/transparency/head")
      return Promise.resolve(
        jsonResponse({
          seq: head.seq,
          entry_hash: head.entry_hash,
          created_at: head.created_at,
          chain_length: chain.length,
          genesis_hash: chain[0].entry_hash,
          protocol: "aqyl-kezek-transparency-ledger",
          protocol_version: 1,
          canonicalization: "hqai-canonical-json-v1",
        }),
      );
    if (path === "/transparency/verify")
      return Promise.resolve(jsonResponse(server));
    if (path === "/transparency/entries")
      return Promise.resolve(
        jsonResponse({
          items: [...chain].reverse(),
          total: chain.length,
          limit: 12,
          offset: 0,
        }),
      );
    const one = /^\/transparency\/entries\/(\d+)$/.exec(path);
    if (one) {
      const entry = chain.find((e) => e.seq === Number(one[1]));
      return Promise.resolve(
        entry
          ? jsonResponse(entry)
          : jsonResponse({ detail: "no ledger entry" }, 404),
      );
    }
    if (path === "/transparency/lookup") {
      const hash = url.searchParams.get("entry_hash");
      const subject = url.searchParams.get("subject");
      return Promise.resolve(
        jsonResponse(
          chain.filter((e) =>
            hash ? e.entry_hash.startsWith(hash) : e.subject === subject,
          ),
        ),
      );
    }
    if (path === "/transparency/export")
      return Promise.resolve(
        new Response(exported, {
          status: 200,
          headers: { "Content-Type": "application/x-ndjson" },
        }),
      );
    return inner(input, init);
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

beforeEach(() => {
  prepareTower();
  window.localStorage.removeItem("hqai.ledger.trustedHead");
});
afterEach(() => {
  cleanup();
  cleanupTower();
});

const serverCard = () => screen.getByTestId("server-verification");
const browserCard = () => screen.getByTestId("browser-verification");

describe("/verify", () => {
  it("shows both verifications as confirmed, with the chain facts", async () => {
    mockLedger();
    renderAt("/verify");
    expect(
      await screen.findByRole("heading", { level: 1, name: t.verify.title }),
    ).toBeVisible();
    await waitFor(() =>
      expect(within(serverCard()).getByText(t.verify.status.ok)).toBeVisible(),
    );
    await waitFor(() =>
      expect(within(browserCard()).getByText(t.verify.status.ok)).toBeVisible(),
    );
    expect(
      within(browserCard()).getByText(t.verify.browser.matchesServer),
    ).toBeVisible();
    expect(within(serverCard()).getByText(String(chain.length))).toBeVisible();
    // the head hash is shortened on screen but its full value is one click away
    expect(
      within(serverCard()).getByTitle(head.entry_hash).textContent,
    ).toMatch(/…/);
    // the recent entries are labelled in words, newest first
    const recent = screen.getByTestId("recent-entries");
    expect(
      within(recent).getAllByText(t.verify.events.specialist_decision).length,
    ).toBe(1);
    expect(screen.getByText(t.verify.motto)).toBeVisible();
    // the browser remembered the head it verified, for the next visit
    expect(
      JSON.parse(window.localStorage.getItem("hqai.ledger.trustedHead") ?? "{}")
        .hash,
    ).toBe(head.entry_hash);
  });

  it("the browser does not trust the server: a tampered export is BROKEN at its entry", async () => {
    const tampered = exportOf(chain).replace(
      '"action":"accept"',
      '"action":"decline"',
    );
    mockLedger({ exported: tampered });
    renderAt("/verify");
    await waitFor(() =>
      expect(within(serverCard()).getByText(t.verify.status.ok)).toBeVisible(),
    );
    await waitFor(() =>
      expect(
        within(browserCard()).getByText(t.verify.status.broken),
      ).toBeVisible(),
    );
    const failure = within(browserCard()).getByRole("alert");
    expect(failure).toHaveTextContent(t.verify.seq(4));
    expect(failure).toHaveTextContent(t.verify.reasons.ENTRY_HASH_MISMATCH);
    expect(failure).toHaveTextContent("ENTRY_HASH_MISMATCH");
    // a broken chain is never remembered as trusted
    expect(window.localStorage.getItem("hqai.ledger.trustedHead")).toBeNull();
  });

  it("shows the server's BROKEN verdict with the entry, reason and subject", async () => {
    mockLedger({ server: serverBroken });
    renderAt("/verify");
    await waitFor(() =>
      expect(
        within(serverCard()).getByText(t.verify.status.broken),
      ).toBeVisible(),
    );
    const failure = within(serverCard()).getByRole("alert");
    expect(failure).toHaveTextContent(t.verify.seq(4));
    expect(failure).toHaveTextContent(t.verify.reasons.COMMITMENT_MISMATCH);
    expect(failure).toHaveTextContent("specialist_decision:41");
  });

  it("checks the head this browser saw before", async () => {
    window.localStorage.setItem(
      "hqai.ledger.trustedHead",
      JSON.stringify({
        seq: 2,
        hash: "e".repeat(64),
        seenAt: "2026-09-27T10:00:00Z",
      }),
    );
    mockLedger();
    renderAt("/verify");
    await waitFor(() =>
      expect(within(browserCard()).getByRole("alert")).toHaveTextContent(
        t.verify.reasons.TRUSTED_HEAD_MISMATCH,
      ),
    );
    window.localStorage.setItem(
      "hqai.ledger.trustedHead",
      JSON.stringify({
        seq: 2,
        hash: chain[1].entry_hash,
        seenAt: "2026-09-27T10:00:00Z",
      }),
    );
    await userEvent.click(
      within(browserCard()).getByRole("button", { name: t.verify.browser.run }),
    );
    await waitFor(() =>
      expect(
        within(browserCard()).getByText(/№2/, { selector: "p" }),
      ).toBeVisible(),
    );
  });

  it("opens a receipt's entry from the link and re-hashes it in the browser", async () => {
    mockLedger();
    renderAt(`/verify?seq=${head.seq}`);
    const entry = await screen.findByTestId("ledger-entry");
    expect(entry).toHaveTextContent(head.subject);
    await waitFor(() =>
      expect(within(entry).getByText(t.verify.lookup.recomputed)).toBeVisible(),
    );
    // the commitment note explains why no comment is shown
    expect(entry).toHaveTextContent(t.verify.lookup.commitmentsNote);
  });

  it("finds entries by hash prefix and by subject, and rejects nonsense", async () => {
    mockLedger();
    renderAt("/verify");
    const input = await screen.findByLabelText(t.verify.lookup.label);
    await userEvent.type(input, chain[1].entry_hash.slice(0, 10));
    await userEvent.click(
      screen.getByRole("button", { name: t.verify.lookup.submit }),
    );
    expect(await screen.findByTestId("ledger-entry")).toHaveTextContent(
      chain[1].subject,
    );
    await userEvent.clear(input);
    await userEvent.type(input, "что-то");
    await userEvent.click(
      screen.getByRole("button", { name: t.verify.lookup.submit }),
    );
    expect(await screen.findByText(t.verify.lookup.invalid)).toBeVisible();
  });

  it("copies the full hash, not the shortened one", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    mockLedger();
    renderAt("/verify");
    await waitFor(() =>
      expect(within(serverCard()).getByText(t.verify.status.ok)).toBeVisible(),
    );
    await userEvent.click(
      within(serverCard()).getByRole("button", {
        name: t.verify.copyHash(head.entry_hash),
      }),
    );
    expect(writeText).toHaveBeenCalledWith(head.entry_hash);
    expect(
      await within(serverCard()).findAllByText(t.verify.copied),
    ).not.toHaveLength(0);
  });

  it("renders nothing private: no salt, no committed text", async () => {
    mockLedger();
    renderAt(`/verify?seq=${head.seq}`);
    await screen.findByTestId("ledger-entry");
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/salt/i);
    expect(text).not.toContain("Согласовано с приёмным отделением");
    expect(text).not.toContain("Иванова");
  });

  it("is complete in Kazakh", async () => {
    setLang("kk");
    mockLedger();
    renderAt("/verify");
    expect(
      await screen.findByRole("heading", { level: 1, name: kk.verify.title }),
    ).toBeVisible();
    await waitFor(() =>
      expect(
        within(browserCard()).getByText(kk.verify.status.ok),
      ).toBeVisible(),
    );
    expect(screen.getByText(kk.verify.server.title)).toBeVisible();
    expect(screen.getByText(kk.verify.motto)).toBeVisible();
    // no Russian copy of this page leaks into the Kazakh one
    const body = document.body.textContent ?? "";
    for (const phrase of [
      ru.verify.title,
      ru.verify.server.title,
      ru.verify.browser.title,
      ru.verify.explain.human.title,
    ])
      expect(body).not.toContain(phrase);
  });
});

describe("Kazakh and Russian copy", () => {
  it("has every key in both languages and no empty or placeholder string", () => {
    const walk = (value: unknown, path: string, out: string[]) => {
      if (typeof value === "string") out.push(`${path}=${value}`);
      else if (Array.isArray(value))
        value.forEach((v, i) => walk(v, `${path}[${i}]`, out));
      else if (value && typeof value === "object")
        for (const [k, v] of Object.entries(value))
          walk(v, `${path}.${k}`, out);
      return out;
    };
    const ruStrings = walk(ru.verify, "verify", []);
    const kkStrings = walk(kk.verify, "verify", []);
    expect(kkStrings.map((s) => s.split("=")[0])).toEqual(
      ruStrings.map((s) => s.split("=")[0]),
    );
    for (const entry of kkStrings) {
      const value = entry.slice(entry.indexOf("=") + 1);
      expect(value.trim()).not.toBe("");
      expect(value).not.toMatch(/TODO|TBD|\?\?\?/);
    }
    // translated, not copied: at least nine in ten Kazakh strings differ from the Russian ones
    const same = ruStrings.filter((s, i) => s === kkStrings[i]).length;
    expect(same / ruStrings.length).toBeLessThan(0.1);
  });
});
