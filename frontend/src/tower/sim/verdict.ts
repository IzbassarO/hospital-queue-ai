/**
 * "Should the specialist step in?" — a yes / no / unclear reading of one alert (or one patient request) built
 * only from published facts and the labelled simulation state. It is an attention verdict with its reasons, never
 * an instruction: the dialog says so next to it.
 */
import { t } from "../../i18n";
import { fmtDate, fmtNumber } from "../../lib/format";
import { daysBetween, flowDecimals, URGENCY_FLOOR_PER_DAY } from "../synthetic";
import type { SimAlert, SimPatient } from "./simulation";

export type Verdict = "yes" | "no" | "unclear";
export interface VerdictReading {
  verdict: Verdict;
  reasons: string[];
}

export function alertVerdict(
  alert: SimAlert,
  waiting: number,
  today: string,
): VerdictReading {
  const r = t.control.verdict.reasons;
  const reasons: string[] = [];
  const lead = alert.crossing ? daysBetween(today, alert.crossing) : null;
  if (alert.phase === "unverified")
    return { verdict: "unclear", reasons: [r.unverified] };
  if (alert.phase === "not_confirmed")
    return { verdict: "no", reasons: [r.notConfirmed] };
  if (alert.phase === "confirmed" && alert.observed !== null)
    reasons.push(
      r.confirmed(fmtNumber(alert.observed, flowDecimals(alert.observed))),
    );
  if (alert.phase === "escalated") reasons.push(r.escalated);
  if (
    alert.lower !== null &&
    alert.threshold !== null &&
    alert.lower > alert.threshold
  )
    reasons.push(r.lowerAbove);
  else if (
    alert.central !== null &&
    alert.threshold !== null &&
    alert.central > alert.threshold
  )
    reasons.push(r.centralAbove);
  if (lead !== null) reasons.push(lead <= 3 ? r.soon(lead) : r.far(lead));
  reasons.push(waiting > 0 ? r.queue(waiting) : r.noQueue);
  if (alert.medianWait !== null)
    reasons.push(r.historyWait(fmtNumber(alert.medianWait, 0), alert.queueNow));
  if (alert.support === "FALLBACK_LIMITED") reasons.push(r.fallback);
  const smallFlow =
    alert.central !== null && alert.central < URGENCY_FLOOR_PER_DAY;
  if (smallFlow)
    reasons.push(
      r.smallFlow(
        fmtNumber(alert.central ?? 0, flowDecimals(alert.central)),
        URGENCY_FLOOR_PER_DAY,
      ),
    );
  if (alert.decision)
    reasons.push(
      r.decided(t.control.decision.actions[alert.decision.action].label),
    );
  const strong =
    !smallFlow &&
    (alert.phase === "confirmed" ||
      alert.phase === "escalated" ||
      alert.severity === "HIGH" ||
      (lead !== null && lead <= 2));
  return { verdict: strong ? "yes" : "no", reasons };
}

export function patientVerdict(
  patient: SimPatient,
  alert: SimAlert | undefined,
  waiting: number,
  today: string,
): VerdictReading {
  const r = t.control.verdict.reasons;
  const reasons: string[] = [r.patientSoon(fmtDate(patient.predictedDate))];
  if (alert) {
    const inner = alertVerdict(alert, waiting, today);
    reasons.push(...inner.reasons.slice(0, 2));
  }
  reasons.push(patient.urgency === "high" ? r.patientUrgent : r.patientPlanned);
  const verdict: Verdict =
    patient.urgency === "high" || alert?.phase === "confirmed" ? "yes" : "no";
  return { verdict, reasons };
}
