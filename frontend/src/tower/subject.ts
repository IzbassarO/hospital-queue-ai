/** Resolve a subject (alert or patient request) of the running simulation into everything the views need. */
import type { SimAlert, SimPatient, SimState } from "./sim/simulation";
import type { Subject } from "./ui";

export interface SubjectView {
  subject: Subject;
  alert: SimAlert | undefined;
  patient: SimPatient | undefined;
  hospital: string;
  profile: string;
  region: string;
  waiting: number;
}

export function resolveSubject(
  subject: Subject,
  state: SimState,
  names: {
    hospital: (org: string) => string;
    profile: (code: string) => string;
    region: (code: string) => string;
  },
): SubjectView | null {
  const patient =
    subject.kind === "patient"
      ? state.patients.find((p) => p.id === subject.id)
      : undefined;
  const alert =
    subject.kind === "alert"
      ? state.alerts.find((a) => a.id === subject.id)
      : patient
        ? state.alerts.find((a) => a.org === patient.org)
        : undefined;
  if (!alert && !patient) return null;
  const org = alert?.org ?? patient?.org ?? "";
  const waiting = state.patients.filter(
    (p) => p.org === org && p.status !== "admitted" && p.status !== "declined",
  ).length;
  return {
    subject,
    alert,
    patient,
    hospital: alert?.hospitalName ?? names.hospital(org),
    profile: alert?.profileName ?? names.profile(patient?.profile ?? ""),
    region: alert?.regionName ?? names.region(patient?.region ?? ""),
    waiting,
  };
}
