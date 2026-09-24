/** The specialist's inbox: every open request, first come first served, then by urgency. */
import type { Urgency } from "../synthetic";
import {
  minutesOf,
  type SimAlert,
  type SimPatient,
  type SimState,
} from "./simulation";

export type Task =
  | {
      kind: "alert";
      id: string;
      day: number;
      time: string;
      order: number;
      alert: SimAlert;
      urgency: Urgency;
    }
  | {
      kind: "patient";
      id: string;
      day: number;
      time: string;
      order: number;
      patient: SimPatient;
      alert: SimAlert | undefined;
      urgency: Urgency;
    };

const URGENCY_RANK: Record<Urgency, number> = {
  high: 0,
  medium: 1,
  planned: 2,
};

export function pendingTasks(state: SimState): Task[] {
  const tasks: Task[] = [];
  for (const e of state.events) {
    if (e.day === state.day && minutesOf(e.time) > state.clock) continue;
    if ((e.kind === "decision_needed" || e.kind === "escalated") && e.alertId) {
      const alert = state.alerts.find((a) => a.id === e.alertId);
      if (
        alert &&
        !alert.decision &&
        (alert.phase === "decision" || alert.phase === "escalated")
      )
        tasks.push({
          kind: "alert",
          id: alert.id,
          day: e.day,
          time: e.time,
          order: e.id,
          alert,
          urgency: alert.severity === "HIGH" ? "high" : "medium",
        });
    }
    if (e.kind === "patient_request" && e.patientId) {
      const patient = state.patients.find((p) => p.id === e.patientId);
      if (patient && patient.status === "request")
        tasks.push({
          kind: "patient",
          id: patient.id,
          day: e.day,
          time: e.time,
          order: e.id,
          patient,
          alert: state.alerts.find((a) => a.org === patient.org),
          urgency: patient.urgency,
        });
    }
  }
  const seen = new Set<string>();
  return tasks
    .filter((t) =>
      seen.has(`${t.kind}:${t.id}`)
        ? false
        : (seen.add(`${t.kind}:${t.id}`), true),
    )
    .sort(
      (a, b) =>
        a.day - b.day ||
        minutesOf(a.time) - minutesOf(b.time) ||
        URGENCY_RANK[a.urgency] - URGENCY_RANK[b.urgency] ||
        a.order - b.order,
    );
}

/** Queue sizes: how many are still waiting within 7, 14 and 30 days of the current date. */
export function waitingWithin(state: SimState, days: number): number {
  const limit = new Date(`${state.date}T00:00:00Z`);
  limit.setUTCDate(limit.getUTCDate() + days);
  const iso = limit.toISOString().slice(0, 10);
  return state.patients.filter(
    (p) =>
      (p.status === "waiting" ||
        p.status === "request" ||
        p.status === "confirmed" ||
        p.status === "delayed") &&
      p.predictedDate <= iso,
  ).length;
}
