/** Localised labels for ledger entries: what an event is, in the operator's words, never a raw event type. */
import { t } from "../i18n";

interface EntryLike {
  event_type: string;
  subject: string;
  payload: Record<string, unknown>;
}

export function eventLabel(entry: EntryLike): string {
  const events = t.verify.events;
  if (entry.event_type === "decision.recorded") {
    const kind = entry.subject.split(":")[0];
    return kind === "hospital_decision"
      ? events.hospital_decision
      : events.specialist_decision;
  }
  const base =
    entry.event_type in events
      ? events[entry.event_type as keyof typeof events]
      : events.other;
  const kind = entry.payload.publication_kind;
  const kindName = typeof kind === "string" ? t.verify.kinds[kind] : undefined;
  return kindName ? `${base}: ${kindName}` : base;
}

export function reasonLabel(code: string | null | undefined): string {
  if (!code) return "";
  return t.verify.reasons[code] ?? code;
}

/** "2026-09-28T15:02:37.273896Z" → "28.09.2026 15:02:37" (UTC, as recorded). */
export function ledgerTime(canonical: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}:\d{2})/.exec(canonical);
  return match
    ? `${match[3]}.${match[2]}.${match[1]} ${match[4]} UTC`
    : canonical;
}
