/**
 * The simulation lives in a module-level store so it survives re-mounts (language switch, a visit to the story
 * and back). One synthetic day per interval while playing. The store is (re)initialised when the seeds change.
 */
import { useEffect, useMemo, useSyncExternalStore } from "react";
import { t } from "../../i18n";
import { fmtDate, fmtNumber } from "../../lib/format";
import type { ScenarioId, SyntheticPatient } from "../synthetic";
import {
  DAY_MINUTES,
  initialState,
  newRunId,
  reduce,
  type AlertSeed,
  type DecisionAction,
  type PatientAction,
  type SimAction,
  type SimState,
  type SimText,
} from "./simulation";

/** Real milliseconds to walk one synthetic day (08:00 → 18:00) at speed ×1. */
export const DAY_MS = 14000;
const TICK_MS = 120;

let state: SimState | null = null;
let seedKey = "";
const listeners = new Set<() => void>();
const STORAGE_KEY = "hqai.sim.v1";
let saveTimer: number | null = null;

/** Persist the running simulation (debounced) so a reload of the page continues where it stopped. */
function scheduleSave() {
  if (typeof window === "undefined" || !state) return;
  if (saveTimer !== null) window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    saveTimer = null;
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ seedKey, state: { ...state, playing: false } }),
      );
    } catch {
      // storage full or unavailable: the simulation simply is not remembered
    }
  }, 300);
}
function restoreSaved(key: string): SimState | null {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as { seedKey?: string; state?: SimState };
    if (saved.seedKey !== key || !saved.state) return null;
    return {
      ...saved.state,
      // states saved before run ids existed get one now
      runId: saved.state.runId || newRunId(),
      playing: false,
      pausedForDecision: false,
    };
  } catch {
    return null;
  }
}
/** Test hook: forget what the browser remembered. */
export function clearSavedSimulation() {
  try {
    globalThis.localStorage?.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
const get = () => state;
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
function dispatch(action: SimAction) {
  if (!state) return;
  const next = reduce(state, action);
  if (next === state) return;
  state = next;
  listeners.forEach((l) => l());
  scheduleSave();
}
/** Test hook: forget the running simulation. */
export function resetSimulationStore() {
  state = null;
  seedKey = "";
}
/** Initialise (or re-seed) the store outside React so hooks never reassign module state. */
function ensureStore(
  key: string,
  origin: string,
  alerts: AlertSeed[],
  patients: SyntheticPatient[],
  dailyBase: number,
  outageRegion: string,
) {
  if (state && seedKey === key) return;
  seedKey = key;
  state =
    restoreSaved(key) ??
    initialState(origin, alerts, patients, dailyBase, outageRegion);
}

/** The sentences the reducer writes into the feed, in the current language. */
export function useSimText(regionName: (code: string) => string): SimText {
  return useMemo<SimText>(
    () => ({
      ...t.control.sim.events,
      actionLabel: (action: DecisionAction) =>
        t.control.decision.actions[action].label,
      patientActionLabel: (action: PatientAction) =>
        t.control.patientDecision.actions[action].label,
      regionName,
      formatNumber: fmtNumber,
      formatDate: fmtDate,
    }),
    [regionName],
  );
}

export function useSimulation(
  origin: string,
  alerts: AlertSeed[],
  patients: SyntheticPatient[],
  dailyBase: number,
  outageRegion: string,
  regionName: (code: string) => string,
  speed: number,
) {
  // The key names the published inputs only (origin + alert ids): synthetic details may settle later without
  // restarting a simulation that is already running.
  const key = `${origin}:${alerts.map((a) => a.id).join(",")}`;
  ensureStore(key, origin, alerts, patients, dailyBase, outageRegion);
  const text = useSimText(regionName);
  const current = useSyncExternalStore(subscribe, get, get) as SimState;
  useEffect(() => {
    if (!current.playing || current.finished) return;
    const perTick = (DAY_MINUTES * TICK_MS * speed) / DAY_MS;
    const timer = window.setInterval(
      () => dispatch({ type: "advance", minutes: perTick, text }),
      TICK_MS,
    );
    return () => window.clearInterval(timer);
  }, [current.playing, current.finished, speed, text]);
  return {
    state: current,
    play: () => dispatch({ type: "play" }),
    pause: () => dispatch({ type: "pause" }),
    step: () => dispatch({ type: "tick", text }),
    /** used by tests and the layout: read-only access to the running simulation */
    reset: () => dispatch({ type: "reset" }),
    setScenario: (scenario: ScenarioId) =>
      dispatch({ type: "scenario", scenario }),
    decide: (alertId: string, action: DecisionAction, comment: string) =>
      dispatch({ type: "decide", alertId, action, comment, text }),
    decidePatient: (
      patientId: string,
      action: PatientAction,
      comment: string,
    ) => dispatch({ type: "patientDecide", patientId, action, comment, text }),
  };
}

/** Read the running simulation from anywhere (layout, explorer); null before a page initialised it. */
export function useSimState(): SimState | null {
  return useSyncExternalStore(subscribe, get, get);
}
export function dispatchSim(action: SimAction): void {
  dispatch(action);
}

export type Simulation = ReturnType<typeof useSimulation>;
export type { SimState };
