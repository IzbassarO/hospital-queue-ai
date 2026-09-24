/**
 * Fourteen-day simulation of the control centre. Pure reducer, seeded: the same scenario always replays the same
 * way. Published values (forecast, threshold, crossing date, severity) are never changed; the synthetic part is the
 * observed flow, the queue, the intra-day feed and the human's decisions. Every event carries a synthetic time of
 * day so the feed reads like a day unfolding.
 */
import {
  addDays,
  daysBetween,
  rng,
  scenarioDef,
  type ScenarioId,
  type SyntheticPatient,
} from "../synthetic";

export const SIM_DAYS = 14;

export interface AlertSeed {
  id: string;
  org: string;
  region: string;
  profile: string;
  hospitalName: string;
  profileName: string;
  regionName: string;
  severity: string;
  rank: number | null;
  central: number | null;
  threshold: number | null;
  lower: number | null;
  upper: number | null;
  coverage: string | null;
  crossing: string | null;
  lead: number | null;
  support: string;
  reasons: string[];
  /** historical median wait (days) of this hospital × profile from the mart, null when unknown */
  medianWait: number | null;
  /** queue of referrals waiting for this hospital × profile at the mart as-of date */
  queueNow: number | null;
}

/** A decision replayed from the database (persisted through the API). */
export interface StoredDecision {
  subject_kind: "alert" | "patient";
  subject_id: string;
  sim_day: number;
  action: string;
  comment: string | null;
}

export type AlertPhase =
  | "forecast"
  | "decision"
  | "confirmed"
  | "not_confirmed"
  | "unverified"
  | "escalated";

export type DecisionAction = "accept" | "decline" | "clarify";
export type PatientAction = "confirm" | "postpone" | "decline";

export interface SimDecision {
  alertId: string;
  day: number;
  action: DecisionAction;
  comment: string;
}
export interface PatientDecision {
  patientId: string;
  day: number;
  action: PatientAction;
  comment: string;
}

export interface SimAlert extends AlertSeed {
  phase: AlertPhase;
  phaseDay: number;
  observed: number | null;
  decision: SimDecision | null;
  missed: boolean;
}

export type PatientStatus =
  | "waiting"
  | "request"
  | "confirmed"
  | "admitted"
  | "delayed"
  | "declined"
  | "unverified";
export interface SimPatient extends SyntheticPatient {
  status: PatientStatus;
  admittedDate: string | null;
  decision: PatientDecision | null;
  /** day the urgent request was raised */
  requestDay: number | null;
}

export type EventKind =
  | "arrivals"
  | "admitted"
  | "delayed"
  | "decision_needed"
  | "patient_request"
  | "confirmed"
  | "not_confirmed"
  | "unverified"
  | "escalated"
  | "decided"
  | "patient_decided"
  | "missed"
  | "finished";

export interface SimEvent {
  id: number;
  day: number;
  /** synthetic time of day, "09:40" */
  time: string;
  kind: EventKind;
  text: string;
  org: string | null;
  alertId: string | null;
  patientId: string | null;
}

export interface SimStats {
  arrivalsToday: number | null;
  arrivalsTotal: number;
  admitted: number;
  delayed: number;
  confirmed: number;
  notConfirmed: number;
  unverified: number;
  decisions: number;
  patientDecisions: number;
  missed: number;
}

export interface SimState {
  origin: string;
  /** identifies one run of the simulation: "Сначала" and a scenario change start a new one, so decisions of the
   * previous run are neither shown nor replayed (they stay in the database as history) */
  runId: string;
  day: number;
  date: string;
  playing: boolean;
  scenario: ScenarioId;
  outageRegion: string;
  alerts: SimAlert[];
  patients: SimPatient[];
  events: SimEvent[];
  stats: SimStats;
  dailyBase: number;
  finished: boolean;
  /** the clock stopped itself because the specialist is needed */
  pausedForDecision: boolean;
  /** minutes since 08:00 of the current day (0..DAY_MINUTES); events reveal as the clock passes their time */
  clock: number;
}

export const DAY_START_HOUR = 8;
export const DAY_MINUTES = 600;
export const minutesOf = (time: string): number => {
  const [h, m] = time.split(":").map(Number);
  return (h - DAY_START_HOUR) * 60 + m;
};
export const clockLabel = (minutes: number): string => {
  const total =
    DAY_START_HOUR * 60 +
    Math.floor(Math.min(DAY_MINUTES, Math.max(0, minutes)));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
};
export const ACTIONABLE: ReadonlySet<EventKind> = new Set([
  "decision_needed",
  "patient_request",
  "escalated",
]);
/** Events already revealed by the clock (all past days, and today's up to the current time). */
export const visibleEvents = (state: SimState): SimEvent[] =>
  state.events.filter(
    (e) => e.day < state.day || minutesOf(e.time) <= state.clock,
  );

export interface SimText {
  arrivals: (n: string) => string;
  arrivalsOutage: (region: string) => string;
  admitted: (n: number) => string;
  delayed: (n: number) => string;
  decisionNeeded: (hospital: string, profile: string) => string;
  patientRequest: (
    id: string,
    hospital: string,
    profile: string,
    date: string,
  ) => string;
  confirmed: (hospital: string, observed: string, threshold: string) => string;
  notConfirmed: (hospital: string) => string;
  unverified: (hospital: string) => string;
  escalated: (hospital: string, profile: string) => string;
  decided: (hospital: string, action: string) => string;
  patientDecided: (id: string, action: string) => string;
  missed: (hospital: string) => string;
  finished: (confirmed: number, decisions: number, lead: string) => string;
  actionLabel: (action: DecisionAction) => string;
  patientActionLabel: (action: PatientAction) => string;
  regionName: (code: string) => string;
  formatNumber: (n: number, decimals: number) => string;
  formatDate: (iso: string) => string;
}

export type SimAction =
  | { type: "tick"; text: SimText }
  | { type: "advance"; minutes: number; text: SimText }
  | { type: "play" }
  | { type: "pause" }
  | { type: "reset" }
  | { type: "restore"; state: SimState }
  | { type: "hydrate"; decisions: StoredDecision[] }
  | { type: "scenario"; scenario: ScenarioId }
  | {
      type: "decide";
      alertId: string;
      action: DecisionAction;
      comment: string;
      text: SimText;
    }
  | {
      type: "patientDecide";
      patientId: string;
      action: PatientAction;
      comment: string;
      text: SimText;
    };

export const newRunId = (): string =>
  `run-${Date.now().toString(36)}-${Math.floor(Math.random() * 1679616)
    .toString(36)
    .padStart(4, "0")}`;

export function initialState(
  origin: string,
  alerts: AlertSeed[],
  patients: SyntheticPatient[],
  dailyBase: number,
  outageRegion: string,
  scenario: ScenarioId = "baseline",
): SimState {
  return {
    origin,
    runId: newRunId(),
    day: 0,
    date: origin,
    playing: false,
    scenario,
    outageRegion,
    alerts: alerts.map((a) => ({
      ...a,
      phase: "forecast",
      phaseDay: 0,
      observed: null,
      decision: null,
      missed: false,
    })),
    patients: patients.map((p) => ({
      ...p,
      status: "waiting",
      admittedDate: null,
      decision: null,
      requestDay: null,
    })),
    events: [],
    stats: {
      arrivalsToday: null,
      arrivalsTotal: 0,
      admitted: 0,
      delayed: 0,
      confirmed: 0,
      notConfirmed: 0,
      unverified: 0,
      decisions: 0,
      patientDecisions: 0,
      missed: 0,
    },
    dailyBase,
    finished: false,
    pausedForDecision: false,
    clock: DAY_MINUTES,
  };
}

const MAX_DECISIONS_PER_DAY = 2;
const MAX_REQUESTS_PER_DAY = 2;

const clock = (hour: number, random: () => number): string =>
  `${String(hour).padStart(2, "0")}:${String(Math.floor(random() * 60)).padStart(2, "0")}`;

function tick(state: SimState, text: SimText, clockAt: number): SimState {
  if (state.finished) return state;
  const day = state.day + 1;
  const date = addDays(state.origin, day);
  const random = rng(20250317 + day * 7919 + state.scenario.length);
  const def = scenarioDef(state.scenario, state.outageRegion);
  const events: SimEvent[] = [];
  let nextId = (state.events.at(-1)?.id ?? 0) + 1;
  const push = (
    kind: EventKind,
    time: string,
    textValue: string,
    org: string | null = null,
    alertId: string | null = null,
    patientId: string | null = null,
  ) =>
    events.push({
      id: nextId++,
      day,
      time,
      kind,
      text: textValue,
      org,
      alertId,
      patientId,
    });
  const stats = { ...state.stats };

  // 08:xx — referrals of the day (synthetic, around the national daily mean of the mart).
  const arrivals = Math.round(
    state.dailyBase * def.national * (0.94 + random() * 0.12),
  );
  stats.arrivalsToday = arrivals;
  stats.arrivalsTotal += arrivals;
  push(
    "arrivals",
    clock(8, random),
    text.arrivals(text.formatNumber(arrivals, 0)),
  );
  if (def.outageRegion)
    push(
      "unverified",
      clock(8, random),
      text.arrivalsOutage(text.regionName(def.outageRegion)),
    );

  // 09–11 — the model asks the specialist ahead of crossings; crossings are checked on their day.
  let requested = 0;
  let askedHuman = false;
  const alerts = state.alerts.map((alert) => {
    const a = { ...alert };
    const crossDay = a.crossing
      ? Math.max(1, daysBetween(state.origin, a.crossing))
      : 4;
    const outage = def.outageRegion !== null && a.region === def.outageRegion;
    const asksHuman =
      a.severity === "HIGH" || (a.severity === "ELEVATED" && crossDay <= 3);
    if (
      a.phase === "forecast" &&
      asksHuman &&
      day >= crossDay - 1 &&
      requested < MAX_DECISIONS_PER_DAY &&
      !outage
    ) {
      requested += 1;
      askedHuman = true;
      a.phase = "decision";
      a.phaseDay = day;
      push(
        "decision_needed",
        clock(9 + requested, random),
        text.decisionNeeded(a.hospitalName, a.profileName),
        a.org,
        a.id,
      );
      return a;
    }
    if (
      (a.phase === "forecast" ||
        a.phase === "decision" ||
        a.phase === "escalated") &&
      day >= crossDay
    ) {
      if (outage) {
        a.phase = "unverified";
        a.phaseDay = day;
        stats.unverified += 1;
        push(
          "unverified",
          clock(12, random),
          text.unverified(a.hospitalName),
          a.org,
          a.id,
        );
        return a;
      }
      if (a.phase === "decision" && !a.decision) {
        a.missed = true;
        stats.missed += 1;
        push(
          "missed",
          clock(12, random),
          text.missed(a.hospitalName),
          a.org,
          a.id,
        );
      }
      const mult = def.multiplier(a.region, a.profileName);
      const central = a.central ?? 0;
      const noise = Math.exp((random() - 0.5) * 0.5);
      const observed = Math.round(central * mult * noise * 10) / 10;
      a.observed = observed;
      a.phaseDay = day;
      if (a.threshold !== null && observed > a.threshold) {
        a.phase = "confirmed";
        stats.confirmed += 1;
        push(
          "confirmed",
          clock(13 + Math.floor(random() * 2), random),
          text.confirmed(
            a.hospitalName,
            text.formatNumber(observed, 1),
            text.formatNumber(a.threshold, 1),
          ),
          a.org,
          a.id,
        );
      } else {
        a.phase = "not_confirmed";
        stats.notConfirmed += 1;
        push(
          "not_confirmed",
          clock(15, random),
          text.notConfirmed(a.hospitalName),
          a.org,
          a.id,
        );
      }
    }
    return a;
  });

  // 16:xx — reactive layer under stress: one elevated series a day may be raised on observed flow.
  if (def.escalation > 0 && random() < def.escalation) {
    const candidate = alerts.find(
      (a) => a.severity === "ELEVATED" && a.phase === "forecast",
    );
    if (candidate) {
      candidate.severity = "HIGH";
      candidate.phase = "escalated";
      candidate.phaseDay = day;
      candidate.lead = Math.max(
        1,
        candidate.crossing ? daysBetween(date, candidate.crossing) : 2,
      );
      askedHuman = true;
      push(
        "escalated",
        clock(16, random),
        text.escalated(candidate.hospitalName, candidate.profileName),
        candidate.org,
        candidate.id,
      );
    }
  }

  // The queue: admissions of the day happen or slip; urgent requests for tomorrow at pressured hospitals.
  const pressured = new Set(
    alerts
      .filter((a) => ["decision", "confirmed", "escalated"].includes(a.phase))
      .map((a) => a.org),
  );
  const tomorrow = addDays(date, 1);
  let admitted = 0;
  let delayed = 0;
  let requests = 0;
  const patients = state.patients.map((p) => {
    if (p.status === "admitted" || p.status === "declined") return p;
    if (def.outageRegion !== null && p.region === def.outageRegion) {
      if (p.predictedDate <= date && p.status !== "unverified")
        return { ...p, status: "unverified" as const };
      return p;
    }
    if (p.predictedDate === date) {
      const slip =
        p.status !== "confirmed" && random() < (def.national > 1 ? 0.3 : 0.16);
      if (slip) {
        delayed += 1;
        return {
          ...p,
          status: "delayed" as const,
          predictedDate: addDays(date, 1 + Math.floor(random() * 3)),
        };
      }
      admitted += 1;
      return { ...p, status: "admitted" as const, admittedDate: date };
    }
    if (
      p.status === "waiting" &&
      p.predictedDate === tomorrow &&
      pressured.has(p.org) &&
      requests < MAX_REQUESTS_PER_DAY
    ) {
      requests += 1;
      askedHuman = true;
      return { ...p, status: "request" as const, requestDay: day };
    }
    return p;
  });
  for (const p of patients)
    if (p.status === "request" && p.requestDay === day) {
      const alert = alerts.find((a) => a.org === p.org);
      push(
        "patient_request",
        clock(10 + Math.floor(random() * 2), random),
        text.patientRequest(
          p.id,
          alert?.hospitalName ?? p.org,
          alert?.profileName ?? p.profile,
          text.formatDate(p.predictedDate),
        ),
        p.org,
        alert?.id ?? null,
        p.id,
      );
    }
  stats.admitted += admitted;
  stats.delayed += delayed;
  if (admitted) push("admitted", clock(17, random), text.admitted(admitted));
  if (delayed) push("delayed", clock(17, random), text.delayed(delayed));

  const finished = day >= SIM_DAYS;
  if (finished) {
    const leads = alerts
      .filter((a) => a.phase === "confirmed" && a.lead !== null)
      .map((a) => a.lead as number);
    const meanLead = leads.length
      ? leads.reduce((s, v) => s + v, 0) / leads.length
      : 0;
    push(
      "finished",
      "18:00",
      text.finished(
        stats.confirmed,
        stats.decisions + stats.patientDecisions,
        text.formatNumber(meanLead, 1),
      ),
    );
  }
  events.sort((a, b) => a.time.localeCompare(b.time) || a.id - b.id);
  void askedHuman;
  return {
    ...state,
    day,
    date,
    playing: finished ? false : state.playing,
    pausedForDecision: false,
    clock: clockAt,
    alerts,
    patients,
    events: [...state.events, ...events],
    stats,
    finished,
  };
}

/** Move the day clock; stop on the first not-yet-revealed actionable event, roll into the next day at 18:00. */
function advance(state: SimState, minutes: number, text: SimText): SimState {
  if (state.finished || !state.playing) return state;
  if (state.clock >= DAY_MINUTES) {
    const next = tick(state, text, 0);
    return next === state ? state : advance(next, 0, text);
  }
  const target = Math.min(DAY_MINUTES, state.clock + minutes);
  const stop = state.events
    .filter(
      (e) =>
        e.day === state.day &&
        ACTIONABLE.has(e.kind) &&
        minutesOf(e.time) > state.clock &&
        minutesOf(e.time) <= target,
    )
    .sort((a, b) => minutesOf(a.time) - minutesOf(b.time))[0];
  if (stop)
    return {
      ...state,
      clock: minutesOf(stop.time),
      playing: false,
      pausedForDecision: true,
    };
  return { ...state, clock: target };
}

const logEvent = (
  state: SimState,
  kind: EventKind,
  textValue: string,
  org: string | null,
  alertId: string | null,
  patientId: string | null,
): SimEvent => ({
  id: (state.events.at(-1)?.id ?? 0) + 1,
  day: state.day,
  time: clockLabel(state.clock),
  kind,
  text: textValue,
  org,
  alertId,
  patientId,
});

export function reduce(state: SimState, action: SimAction): SimState {
  switch (action.type) {
    case "tick":
      return tick(state, action.text, DAY_MINUTES);
    case "advance":
      return advance(state, action.minutes, action.text);
    case "play":
      return state.finished
        ? state
        : { ...state, playing: true, pausedForDecision: false };
    case "pause":
      return { ...state, playing: false, pausedForDecision: false };
    case "restore":
      return { ...action.state, playing: false, pausedForDecision: false };
    case "hydrate": {
      // Decisions stored on the server: applied once to subjects that have no decision yet, without new events.
      let alerts = state.alerts;
      let patients = state.patients;
      let count = 0;
      for (const d of action.decisions) {
        if (d.subject_kind === "alert") {
          const alert = alerts.find((a) => a.id === d.subject_id);
          if (!alert || alert.decision) continue;
          if (!["accept", "decline", "clarify"].includes(d.action)) continue;
          alerts = alerts.map((a) =>
            a.id === alert.id
              ? {
                  ...a,
                  decision: {
                    alertId: a.id,
                    day: d.sim_day,
                    action: d.action as DecisionAction,
                    comment: d.comment ?? "",
                  },
                }
              : a,
          );
          count += 1;
        } else {
          const patient = patients.find((p) => p.id === d.subject_id);
          if (!patient || patient.decision) continue;
          if (!["confirm", "decline", "postpone"].includes(d.action)) continue;
          const action = d.action as PatientAction;
          patients = patients.map((p) =>
            p.id === patient.id
              ? {
                  ...p,
                  decision: {
                    patientId: p.id,
                    day: d.sim_day,
                    action,
                    comment: d.comment ?? "",
                  },
                  status:
                    p.status === "admitted"
                      ? p.status
                      : action === "confirm"
                        ? "confirmed"
                        : action === "postpone"
                          ? "delayed"
                          : "declined",
                }
              : p,
          );
          count += 1;
        }
      }
      if (count === 0) return state;
      return { ...state, alerts, patients };
    }
    case "reset":
      return initialState(
        state.origin,
        state.alerts.map(seedOf),
        state.patients.map(patientSeedOf),
        state.dailyBase,
        state.outageRegion,
        state.scenario,
      );
    case "scenario":
      return initialState(
        state.origin,
        state.alerts.map(seedOf),
        state.patients.map(patientSeedOf),
        state.dailyBase,
        state.outageRegion,
        action.scenario,
      );
    case "decide": {
      const alert = state.alerts.find((a) => a.id === action.alertId);
      if (!alert || alert.decision) return state;
      const decision: SimDecision = {
        alertId: alert.id,
        day: state.day,
        action: action.action,
        comment: action.comment,
      };
      return {
        ...state,
        alerts: state.alerts.map((a) =>
          a.id === alert.id ? { ...a, decision } : a,
        ),
        stats: { ...state.stats, decisions: state.stats.decisions + 1 },
        events: [
          ...state.events,
          logEvent(
            state,
            "decided",
            action.text.decided(
              alert.hospitalName,
              action.text.actionLabel(action.action),
            ),
            alert.org,
            alert.id,
            null,
          ),
        ],
      };
    }
    case "patientDecide": {
      const patient = state.patients.find((p) => p.id === action.patientId);
      if (!patient || patient.decision) return state;
      const decision: PatientDecision = {
        patientId: patient.id,
        day: state.day,
        action: action.action,
        comment: action.comment,
      };
      const status: PatientStatus =
        action.action === "confirm"
          ? "confirmed"
          : action.action === "postpone"
            ? "delayed"
            : "declined";
      const predictedDate =
        action.action === "postpone"
          ? addDays(patient.predictedDate, 3)
          : patient.predictedDate;
      return {
        ...state,
        patients: state.patients.map((p) =>
          p.id === patient.id ? { ...p, decision, status, predictedDate } : p,
        ),
        stats: {
          ...state.stats,
          patientDecisions: state.stats.patientDecisions + 1,
        },
        events: [
          ...state.events,
          logEvent(
            state,
            "patient_decided",
            action.text.patientDecided(
              patient.id,
              action.text.patientActionLabel(action.action),
            ),
            patient.org,
            null,
            patient.id,
          ),
        ],
      };
    }
    default:
      return state;
  }
}

const seedOf = (a: SimAlert): AlertSeed => ({
  id: a.id,
  org: a.org,
  region: a.region,
  profile: a.profile,
  hospitalName: a.hospitalName,
  profileName: a.profileName,
  regionName: a.regionName,
  severity: a.severity,
  rank: a.rank,
  central: a.central,
  threshold: a.threshold,
  lower: a.lower,
  upper: a.upper,
  coverage: a.coverage,
  crossing: a.crossing,
  lead: a.lead,
  support: a.support,
  reasons: a.reasons,
  medianWait: a.medianWait,
  queueNow: a.queueNow,
});
const patientSeedOf = (p: SimPatient): SyntheticPatient => ({
  id: p.id,
  org: p.org,
  region: p.region,
  profile: p.profile,
  referralDate: p.referralDate,
  predictedDate: p.predictedDate,
  predictedWait: p.predictedWait,
  urgency: p.urgency,
});

export const pendingDecisions = (state: SimState): SimAlert[] =>
  state.alerts.filter(
    (a) => (a.phase === "decision" || a.phase === "escalated") && !a.decision,
  );
export const pendingRequests = (state: SimState): SimPatient[] =>
  state.patients.filter((p) => p.status === "request");
