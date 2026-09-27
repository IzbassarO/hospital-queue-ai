/**
 * Synthetic layer of the control centre. Everything the demo generates in the browser lives in this folder: the
 * pseudonymous queue (Н-####), the parameters of the day simulation and the scenario multipliers, read from
 * config.json and scenarios.json and seeded so the demo replays the same way. Nothing here is presented as
 * measured; published forecasts, thresholds, severities, crossing dates and ranks are never touched. The product
 * imports this module through src/tower/synthetic.ts only (README.md).
 */
import type { ScenarioId } from "../tower/synthetic";
import configJson from "./config.json";
import {
  makeGeneratePatients,
  makeScenarioDef,
  parseConfig,
  parseScenarios,
  type ScenariosJson,
  type SyntheticConfig,
} from "./generate";
import scenariosJson from "./scenarios.json";

/** `enabled` of config.json, unless the bundle was built with VITE_SYNTHETIC=off. */
export const syntheticEnabled = (
  enabled: boolean,
  env: string | undefined,
): boolean => enabled && env !== "off";

export const config: SyntheticConfig = parseConfig(
  configJson satisfies SyntheticConfig,
);
export const scenarios: ScenariosJson = parseScenarios(
  scenariosJson satisfies ScenariosJson,
);

export const SYNTHETIC_ENABLED = syntheticEnabled(
  config.enabled,
  import.meta.env.VITE_SYNTHETIC,
);
export const SYNTHETIC_SEED = config.seed;
export const CROSSING_FALLBACK_DAY = config.crossingFallbackDay;
export const QUEUE = config.queue;
export const SIMULATION = config.simulation;
/** scenario chips in the order of scenarios.json */
export const SCENARIO_IDS = Object.keys(scenarios) as ScenarioId[];
export const scenarioDef = makeScenarioDef(scenarios);
export const generatePatients = makeGeneratePatients(
  QUEUE,
  CROSSING_FALLBACK_DAY,
  SYNTHETIC_SEED,
);
