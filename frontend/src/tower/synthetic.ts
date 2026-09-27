/**
 * Seam between the product and the synthetic layer (src/synthetic): the only product module that imports it.
 * The types below describe what the product consumes; the layer fills them from its JSON files. To ship without
 * any synthetic data, delete src/synthetic and point the export line at the end of this file at "./synthetic-off".
 */
import type { Urgency } from "./urgency";

export type ScenarioId = "baseline" | "surge" | "season" | "outage";

export interface ScenarioDef {
  id: ScenarioId;
  /** referral multiplier for a series; 1 = as forecast */
  multiplier: (regionCode: string, profileName: string) => number;
  /** national multiplier for the arrivals counter */
  national: number;
  /** region whose data stops arriving */
  outageRegion: string | null;
  /** chance per day that an elevated series escalates on observed flow */
  escalation: number;
}

/** What one published alert contributes to the queue generator (an AlertSeed satisfies it). */
export interface QueueSeed {
  org: string;
  region: string;
  profile: string;
  severity: string;
  central: number | null;
  crossing: string | null;
  lead: number | null;
  support?: string;
  medianWait?: number | null;
  queueNow?: number | null;
}

export interface SyntheticPatient {
  id: string;
  org: string;
  region: string;
  profile: string;
  referralDate: string;
  predictedDate: string;
  predictedWait: number;
  urgency: Urgency;
}

/** Parameters of the pseudonymous queue (config.json → queue). Waits and queue days are never below one. */
export interface QueueParams {
  /** id = prefix + zero-padded counter, "Н-1034" */
  idPrefix: string;
  idDigits: number;
  counterStart: number;
  /** the counter jumps by 1..counterStepMax between two ids */
  counterStepMax: number;
  /** central forecast assumed for a series that has none */
  centralFallback: number;
  /** referrals per day of a series = clamp(round(central / divisor), min, max) */
  perDay: { divisor: number; min: number; max: number };
  /** queue size when the mart knows the queue: round(clamp(queueNow × share, min, max)) */
  fromQueue: { share: number; min: number; max: number };
  /** queue size otherwise: min(max, base + random × perDay × perDayFactor) */
  count: { base: number; perDayFactor: number; max: number };
  /** share of referrals placed in the forecast window around the crossing; the rest go further down the queue */
  windowShare: number;
  /** window day = clamp(crossDay + offset + random × spread, min, max) */
  window: { offset: number; spread: number; min: number; max: number };
  /** tail day = start + random × spread */
  tail: { start: number; spread: number };
  /** wait = median wait of the hospital × profile (or fallbackDays) × (jitterMin + random × jitterSpread) */
  wait: { fallbackDays: number; jitterMin: number; jitterSpread: number };
}

/** Parameters of the day simulation (config.json → simulation). */
export interface SimulationParams {
  days: number;
  dayStartHour: number;
  dayMinutes: number;
  /** real milliseconds to walk one synthetic day at speed ×1, and the interval between clock steps */
  dayMs: number;
  tickMs: number;
  /** seed of a day = seed + day × daySeedStep (+ the length of the scenario name) */
  daySeedStep: number;
  /** national referrals per day when the mart has no 28-day total */
  dailyBaseFallback: number;
  /** arrivals = daily base × national multiplier × (min + random × spread) */
  arrivalsNoise: { min: number; spread: number };
  decisionsPerDay: number;
  requestsPerDay: number;
  /** the model asks the specialist this many days before the crossing */
  askDaysBefore: number;
  /** an ELEVATED series asks the specialist only when it crosses within this many days */
  elevatedAskWithinDays: number;
  /** observed flow = central × multiplier × exp((random − 0.5) × observedNoiseLog) */
  observedNoiseLog: number;
  /** lead time given to an escalated series without a crossing date */
  escalationLeadFallback: number;
  /** chance that a planned admission slips (stressed = national multiplier above 1) */
  slipChance: { normal: number; stressed: number };
  /** a slipped admission moves by min + random × spread days */
  slipDays: { min: number; spread: number };
  /** days a specialist's "postpone" moves an admission */
  postponeDays: number;
  /** synthetic hour of each event kind; a spread adds random whole hours */
  hours: {
    arrivals: number;
    decision: number;
    request: number;
    requestSpread: number;
    crossing: number;
    confirmed: number;
    confirmedSpread: number;
    notConfirmed: number;
    escalated: number;
    admissions: number;
    finished: string;
  };
}

export {
  CROSSING_FALLBACK_DAY,
  generatePatients,
  QUEUE,
  SCENARIO_IDS,
  scenarioDef,
  SIMULATION,
  SYNTHETIC_ENABLED,
  SYNTHETIC_SEED,
} from "../synthetic";
