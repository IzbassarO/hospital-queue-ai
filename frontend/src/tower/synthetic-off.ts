/**
 * Stand-in for the synthetic layer once src/synthetic is deleted: the same names as the layer's index, nothing
 * generated. Point the export line at the end of ./synthetic.ts here; nothing else in the product changes.
 */
import type {
  QueueParams,
  QueueSeed,
  ScenarioDef,
  ScenarioId,
  SimulationParams,
  SyntheticPatient,
} from "./synthetic";

export const SYNTHETIC_ENABLED = false;
export const SYNTHETIC_SEED = 0;
export const CROSSING_FALLBACK_DAY = 1;
export const QUEUE: QueueParams = {
  idPrefix: "",
  idDigits: 0,
  counterStart: 0,
  counterStepMax: 1,
  centralFallback: 0,
  perDay: { divisor: 1, min: 0, max: 0 },
  fromQueue: { share: 0, min: 0, max: 0 },
  count: { base: 0, perDayFactor: 0, max: 0 },
  windowShare: 0,
  window: { offset: 0, spread: 0, min: 1, max: 1 },
  tail: { start: 1, spread: 0 },
  wait: { fallbackDays: 1, jitterMin: 1, jitterSpread: 0 },
};
export const SIMULATION: SimulationParams = {
  days: 14,
  dayStartHour: 8,
  dayMinutes: 600,
  dayMs: 14000,
  tickMs: 120,
  daySeedStep: 1,
  dailyBaseFallback: 0,
  arrivalsNoise: { min: 1, spread: 0 },
  decisionsPerDay: 0,
  requestsPerDay: 0,
  askDaysBefore: 0,
  elevatedAskWithinDays: 0,
  observedNoiseLog: 0,
  escalationLeadFallback: 1,
  slipChance: { normal: 0, stressed: 0 },
  slipDays: { min: 0, spread: 0 },
  postponeDays: 0,
  hours: {
    arrivals: 8,
    decision: 9,
    request: 10,
    requestSpread: 0,
    crossing: 12,
    confirmed: 13,
    confirmedSpread: 0,
    notConfirmed: 15,
    escalated: 16,
    admissions: 17,
    finished: "18:00",
  },
};
export const SCENARIO_IDS: ScenarioId[] = ["baseline"];
/** Same signatures as the layer's generators, so no call site changes. */
export const scenarioDef = (
  id: ScenarioId,
  _outageRegion: string,
): ScenarioDef => ({
  id,
  multiplier: () => 1,
  national: 1,
  outageRegion: null,
  escalation: 0,
});
export const generatePatients = (
  _seeds: QueueSeed[],
  _origin: string,
  _fallbackWait?: number,
  _seed?: number,
): SyntheticPatient[] => [];
