/**
 * Generators of the synthetic layer, driven by config.json and scenarios.json: the pseudonymous queue around each
 * published crossing window and the scenario definitions of the day simulation. Everything is seeded, so the demo
 * replays the same way; nothing here reads or changes a published value.
 */
import { bool, nullable, num, object, record, str } from "../api/schema";
import { addDays, daysBetween } from "../lib/dates";
import { rng } from "../lib/seeded";
import type {
  QueueParams,
  QueueSeed,
  ScenarioDef,
  ScenarioId,
  SimulationParams,
  SyntheticPatient,
} from "../tower/synthetic";
import { urgencyOf } from "../tower/urgency";

export interface SyntheticConfig {
  /** master switch of the layer; a build with VITE_SYNTHETIC=off overrides it */
  enabled: boolean;
  /** seed of every generator; the day simulation derives its daily seeds from it */
  seed: number;
  /** day of the horizon assumed for a series without a published crossing date */
  crossingFallbackDay: number;
  queue: QueueParams;
  simulation: SimulationParams;
}

export interface ScenarioJson {
  /** referral multiplier of every series; 1 = as forecast */
  multiplier: number;
  /** profiles whose registry name matches the pattern (a case-insensitive regular expression) get their own */
  profile: { pattern: string; multiplier: number } | null;
  /** national multiplier of the arrivals counter */
  national: number;
  /** chance per day that an elevated series escalates on observed flow */
  escalation: number;
  /** the region with the most alerts stops sending data */
  outage: boolean;
}
export type ScenariosJson = Record<ScenarioId, ScenarioJson>;

/** The scenario ids the product knows (tower/synthetic.ts: ScenarioId); scenarios.json must list exactly these. */
export const SCENARIO_KEYS = Object.keys({
  baseline: 0,
  surge: 0,
  season: 0,
  outage: 0,
} satisfies Record<ScenarioId, 0>) as ScenarioId[];

const configSchema = object({
  enabled: bool,
  seed: num,
  crossingFallbackDay: num,
  queue: object({
    idPrefix: str,
    idDigits: num,
    counterStart: num,
    counterStepMax: num,
    centralFallback: num,
    perDay: object({ divisor: num, min: num, max: num }),
    fromQueue: object({ share: num, min: num, max: num }),
    count: object({ base: num, perDayFactor: num, max: num }),
    windowShare: num,
    window: object({ offset: num, spread: num, min: num, max: num }),
    tail: object({ start: num, spread: num }),
    wait: object({ fallbackDays: num, jitterMin: num, jitterSpread: num }),
  }),
  simulation: object({
    days: num,
    dayStartHour: num,
    dayMinutes: num,
    dayMs: num,
    tickMs: num,
    daySeedStep: num,
    dailyBaseFallback: num,
    arrivalsNoise: object({ min: num, spread: num }),
    decisionsPerDay: num,
    requestsPerDay: num,
    askDaysBefore: num,
    elevatedAskWithinDays: num,
    observedNoiseLog: num,
    escalationLeadFallback: num,
    slipChance: object({ normal: num, stressed: num }),
    slipDays: object({ min: num, spread: num }),
    postponeDays: num,
    hours: object({
      arrivals: num,
      decision: num,
      request: num,
      requestSpread: num,
      crossing: num,
      confirmed: num,
      confirmedSpread: num,
      notConfirmed: num,
      escalated: num,
      admissions: num,
      finished: str,
    }),
  }),
});

const scenarioSchema = object({
  multiplier: num,
  profile: nullable(object({ pattern: str, multiplier: num })),
  national: num,
  escalation: num,
  outage: bool,
});

/** config.json checked field by field; a wrong or missing field names itself ("config.json.queue.windowShare"). */
export function parseConfig(value: unknown): SyntheticConfig {
  return configSchema.parse(value, "config.json");
}

/** scenarios.json checked against the product's scenario ids; every pattern must be a valid regular expression. */
export function parseScenarios(value: unknown): ScenariosJson {
  const raw = record(scenarioSchema).parse(value, "scenarios.json");
  const keys = Object.keys(raw);
  const missing = SCENARIO_KEYS.filter((k) => !keys.includes(k));
  const unknown = keys.filter((k) => !(SCENARIO_KEYS as string[]).includes(k));
  if (missing.length || unknown.length)
    throw new Error(
      `scenarios.json: expected exactly ${SCENARIO_KEYS.join(", ")}` +
        (missing.length ? `; missing ${missing.join(", ")}` : "") +
        (unknown.length
          ? `; unknown ${unknown.join(", ")} (add them to ScenarioId in tower/synthetic.ts first)`
          : ""),
    );
  for (const [id, s] of Object.entries(raw))
    if (s.profile) {
      try {
        new RegExp(s.profile.pattern, "i");
      } catch {
        throw new Error(
          `scenarios.json.${id}.profile.pattern: not a regular expression`,
        );
      }
    }
  return raw as ScenariosJson;
}

/** Scenario definitions the simulation reads; an id it does not know (an old saved state) falls back to baseline. */
export function makeScenarioDef(scenarios: ScenariosJson) {
  return (id: ScenarioId, outageRegion: string): ScenarioDef => {
    const s = scenarios[id] ?? scenarios.baseline;
    const profile = s.profile
      ? {
          test: new RegExp(s.profile.pattern, "i"),
          value: s.profile.multiplier,
        }
      : null;
    return {
      id,
      multiplier: profile
        ? (_region, profileName) =>
            profile.test.test(profileName) ? profile.value : s.multiplier
        : () => s.multiplier,
      national: s.national,
      outageRegion: s.outage ? outageRegion : null,
      escalation: s.escalation,
    };
  };
}

/**
 * Pseudonymous queue entries around each alert's crossing window. Counts scale with the mart queue of the
 * hospital × profile, else with the central forecast; waits follow the hospital's historical median.
 */
export function makeGeneratePatients(
  queue: QueueParams,
  crossingFallbackDay: number,
  defaultSeed: number,
) {
  return function generatePatients(
    seeds: QueueSeed[],
    origin: string,
    fallbackWait: number = queue.wait.fallbackDays,
    seed: number = defaultSeed,
  ): SyntheticPatient[] {
    const random = rng(seed);
    const out: SyntheticPatient[] = [];
    let counter = queue.counterStart;
    for (const s of seeds) {
      const perDay = Math.max(
        queue.perDay.min,
        Math.min(
          queue.perDay.max,
          Math.round(
            (s.central ?? queue.centralFallback) / queue.perDay.divisor,
          ),
        ),
      );
      const fromQueue =
        s.queueNow != null && s.queueNow > 0
          ? Math.round(
              Math.min(
                queue.fromQueue.max,
                Math.max(
                  queue.fromQueue.min,
                  s.queueNow * queue.fromQueue.share,
                ),
              ),
            )
          : null;
      const count =
        fromQueue ??
        Math.min(
          queue.count.max,
          queue.count.base +
            Math.floor(random() * perDay * queue.count.perDayFactor),
        );
      const typicalWait = Math.max(1, Math.round(s.medianWait ?? fallbackWait));
      const crossDay = s.crossing
        ? Math.max(1, daysBetween(origin, s.crossing))
        : crossingFallbackDay;
      for (let i = 0; i < count; i++) {
        const predictedDay =
          random() < queue.windowShare
            ? Math.max(
                queue.window.min,
                Math.min(
                  queue.window.max,
                  crossDay +
                    Math.floor(random() * queue.window.spread) +
                    queue.window.offset,
                ),
              )
            : queue.tail.start + Math.floor(random() * queue.tail.spread);
        const wait = Math.max(
          1,
          Math.round(
            typicalWait *
              (queue.wait.jitterMin + random() * queue.wait.jitterSpread),
          ),
        );
        counter += 1 + Math.floor(random() * queue.counterStepMax);
        out.push({
          id: `${queue.idPrefix}${String(counter).padStart(queue.idDigits, "0")}`,
          org: s.org,
          region: s.region,
          profile: s.profile,
          referralDate: addDays(origin, predictedDay - wait),
          predictedDate: addDays(origin, predictedDay),
          predictedWait: wait,
          urgency: urgencyOf(s.severity, s.lead, s.central, s.support ?? null),
        });
      }
    }
    return out.sort((a, b) => a.predictedDate.localeCompare(b.predictedDate));
  };
}
