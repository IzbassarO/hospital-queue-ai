/**
 * The synthetic layer (src/synthetic): its JSON files validate against the product's types, the switch behaves, and
 * the shipped values replay the queue and the fourteen-day simulation exactly as captured before the move to JSON.
 * A deliberate change of config.json or scenarios.json must come with a re-captured fixtures/synthetic-baseline.json.
 */
import { describe, expect, it } from "vitest";
import configJson from "../synthetic/config.json";
import { parseConfig, parseScenarios } from "../synthetic/generate";
import scenariosJson from "../synthetic/scenarios.json";
import {
  config,
  generatePatients,
  scenarioDef,
  SCENARIO_IDS,
  SYNTHETIC_ENABLED,
  syntheticEnabled,
} from "../synthetic";
import {
  confirmedBySource,
  initialState,
  pendingDecisions,
  pendingRequests,
  reduce,
  SIM_DAYS,
  type AlertSeed,
  type SimState,
  type SimText,
} from "../tower/sim/simulation";
import baseline from "./fixtures/synthetic-baseline.json";

const alerts = baseline.alerts as AlertSeed[];

/** Language-free sentences: the replay compares structure, not copy. */
const text: SimText = {
  arrivals: (n) => `arrivals ${n}`,
  arrivalsOutage: (r) => `outage ${r}`,
  admitted: (n) => `admitted ${n}`,
  delayed: (n) => `delayed ${n}`,
  decisionNeeded: (h, p) => `decision ${h} ${p}`,
  patientRequest: (id, h, p, d) => `request ${id} ${h} ${p} ${d}`,
  confirmed: (h, o, th) => `confirmed ${h} ${o} ${th}`,
  notConfirmed: (h) => `not_confirmed ${h}`,
  unverified: (h) => `unverified ${h}`,
  escalated: (h, p) => `escalated ${h} ${p}`,
  decided: (h, a) => `decided ${h} ${a}`,
  patientDecided: (id, a) => `patient_decided ${id} ${a}`,
  missed: (h) => `missed ${h}`,
  finished: (c, d, l) => `finished ${c} ${d} ${l}`,
  actionLabel: (a) => a,
  patientActionLabel: (a) => a,
  regionName: (c) => c,
  formatNumber: (n, d) => n.toFixed(d),
  formatDate: (iso) => iso,
};
const row = (p: SimState["patients"][number]) =>
  `${p.id}|${p.status}|${p.predictedDate}|${p.requestDay ?? ""}`;
const snapshot = (s: SimState, prev: SimState) => ({
  day: s.day,
  date: s.date,
  stats: s.stats,
  events: s.events
    .filter((e) => e.day === s.day)
    .map((e) => [e.time, e.kind, e.text, e.org, e.alertId, e.patientId]),
  alerts: s.alerts.map(
    (a) =>
      `${a.id}|${a.phase}|${a.observedFlow ?? ""}|${a.severity}|${a.lead ?? ""}|${a.missed}`,
  ),
  patientsChanged: s.patients
    .map(row)
    .filter((r, i) => r !== row(prev.patients[i])),
});

describe("synthetic layer: data files", () => {
  it("config.json and scenarios.json validate against the product types", () => {
    expect(parseConfig(configJson)).toEqual(configJson);
    expect(parseScenarios(scenariosJson)).toEqual(scenariosJson);
    expect(config).toEqual(configJson);
    expect(SCENARIO_IDS).toEqual(["baseline", "surge", "season", "outage"]);
  });

  it("a wrong or missing field names itself", () => {
    const queue = { ...configJson.queue, windowShare: "two thirds" };
    expect(() => parseConfig({ ...configJson, queue })).toThrow(
      "config.json.queue.windowShare: expected number, got string",
    );
    const simulation = Object.fromEntries(
      Object.entries(configJson.simulation).filter(([k]) => k !== "slipDays"),
    );
    expect(() => parseConfig({ ...configJson, simulation })).toThrow(
      "config.json.simulation.slipDays: expected a field",
    );
  });

  it("scenarios.json must list exactly the product's scenarios, each with a valid pattern", () => {
    const missing = Object.fromEntries(
      Object.entries(scenariosJson).filter(([k]) => k !== "outage"),
    );
    expect(() => parseScenarios(missing)).toThrow(/missing outage/);
    expect(() =>
      parseScenarios({ ...scenariosJson, storm: scenariosJson.surge }),
    ).toThrow(/unknown storm/);
    const season = {
      ...scenariosJson.season,
      profile: { pattern: "(", multiplier: 1.5 },
    };
    expect(() => parseScenarios({ ...scenariosJson, season })).toThrow(
      "scenarios.json.season.profile.pattern: not a regular expression",
    );
  });

  it("scenario definitions come from scenarios.json", () => {
    const season = scenarioDef("season", "39");
    expect(season.multiplier("71", "Педиатрия")).toBe(1.5);
    expect(season.multiplier("71", "Хирургия")).toBe(1.03);
    expect(season.national).toBe(1.12);
    expect(season.outageRegion).toBeNull();
    expect(scenarioDef("outage", "39").outageRegion).toBe("39");
    expect(scenarioDef("baseline", "39").escalation).toBe(0.05);
  });

  it("the switch: config.json enables, VITE_SYNTHETIC=off wins", () => {
    expect(syntheticEnabled(true, undefined)).toBe(true);
    expect(syntheticEnabled(true, "on")).toBe(true);
    expect(syntheticEnabled(true, "off")).toBe(false);
    expect(syntheticEnabled(false, undefined)).toBe(false);
    expect(SYNTHETIC_ENABLED).toBe(true);
  });
});

describe("synthetic layer: replay", () => {
  it("generatePatients reproduces the queue captured before the move to JSON", () => {
    const patients = generatePatients(
      alerts,
      baseline.origin,
      baseline.fallbackWait,
    );
    expect(patients.slice(0, 5).map((p) => [p.id, p.predictedDate])).toEqual([
      ["Н-1034", "2025-03-19"],
      ["Н-1028", "2025-03-23"],
      ["Н-1037", "2025-03-24"],
      ["Н-1058", "2025-03-24"],
      ["Н-1014", "2025-03-25"],
    ]);
    expect(patients).toEqual(baseline.patients);
  });

  it.each(SCENARIO_IDS)(
    "the fourteen-day simulation replays the %s scenario as captured",
    (scenario) => {
      const patients = generatePatients(
        alerts,
        baseline.origin,
        baseline.fallbackWait,
      );
      let s = initialState(
        baseline.origin,
        alerts,
        patients,
        baseline.dailyBase,
        baseline.outageRegion,
        scenario,
      );
      const days = [];
      for (let d = 1; d <= config.simulation.days; d++) {
        const prev = s;
        s = reduce(s, { type: "tick", text });
        if (scenario === "baseline" && d === 2) {
          const alert = pendingDecisions(s)[0];
          if (alert)
            s = reduce(s, {
              type: "decide",
              alertId: alert.id,
              action: "accept",
              comment: "ok",
              text,
            });
        }
        if (scenario === "surge") {
          const request = pendingRequests(s)[0];
          if (request)
            s = reduce(s, {
              type: "patientDecide",
              patientId: request.id,
              action: "postpone",
              comment: "",
              text,
            });
        }
        days.push(snapshot(s, prev));
      }
      expect(s.finished).toBe(true);
      expect(days).toEqual(baseline.replays[scenario]);
    },
  );
});

/**
 * Confirmation of a crossing must prefer the real outcome: the data mart holds observed registrations for the days
 * after the origin, and only a day it does not cover may fall back to the synthetic flow. The baseline fixture
 * carries no `observed`, so the recorded replay above is the fall-back path; these cases add the facts.
 */
describe("crossing confirmation: the fact first", () => {
  const CROSSING_DAY = 2;
  const CROSSING_DATE = "2025-03-19";
  const withFact = (value: number): AlertSeed[] =>
    alerts.map((a, i) =>
      i === 0 ? { ...a, observed: { [CROSSING_DATE]: value } } : a,
    );
  const run = (seeds: AlertSeed[], days = CROSSING_DAY) => {
    const patients = generatePatients(
      seeds,
      baseline.origin,
      baseline.fallbackWait,
    );
    let s = initialState(
      baseline.origin,
      seeds,
      patients,
      baseline.dailyBase,
      baseline.outageRegion,
      "baseline",
    );
    for (let d = 1; d <= days; d++) s = reduce(s, { type: "tick", text });
    return s;
  };

  it("without a fact the crossing is checked against the synthetic flow and says so", () => {
    const a1 = run(alerts).alerts[0];
    expect(a1.observedSource).toBe("synthetic");
    expect(a1.observedFlow).toBe(6.1);
    expect(a1.phase).toBe("confirmed");
    expect(confirmedBySource(run(alerts), "fact")).toHaveLength(0);
  });

  it("a real observed day above the reference confirms as a fact, not as synthetic noise", () => {
    const state = run(withFact(9));
    const a1 = state.alerts[0];
    expect(a1.observedSource).toBe("fact");
    expect(a1.observedFlow).toBe(9);
    expect(a1.phase).toBe("confirmed");
    expect(confirmedBySource(state, "fact").map((a) => a.id)).toEqual(["a1"]);
  });

  it("a real observed day below the reference does not confirm, even where the synthetic flow would", () => {
    const a1 = run(withFact(0)).alerts[0];
    expect(a1.observedSource).toBe("fact");
    expect(a1.observedFlow).toBe(0);
    expect(a1.phase).toBe("not_confirmed");
  });

  it("facts never move the seeded stream: the synthetic day is identical with and without them", () => {
    const plain = run(alerts, SIM_DAYS);
    const facts = run(withFact(0), SIM_DAYS);
    const arrivals = (s: SimState) =>
      s.events.filter((e) => e.kind === "arrivals").map((e) => e.text);
    expect(facts.stats.arrivalsTotal).toBe(plain.stats.arrivalsTotal);
    expect(arrivals(facts)).toEqual(arrivals(plain));
    expect(facts.alerts.slice(1).map((a) => a.observedFlow)).toEqual(
      plain.alerts.slice(1).map((a) => a.observedFlow),
    );
  });
});
