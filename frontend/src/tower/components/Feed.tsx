/**
 * The feed: a day unfolding card by card as the clock passes each event's time. Newest on top, a day header per
 * day, actionable cards carry the "needs you" mark and open the subject.
 */
import { useMemo } from "react";
import { t } from "../../i18n";
import { fmtDate } from "../../lib/format";
import {
  ACTIONABLE,
  clockLabel,
  visibleEvents,
  type SimEvent,
  type SimState,
} from "../sim/simulation";
import type { Subject } from "../ui";

const ICON: Record<SimEvent["kind"], string> = {
  arrivals: "↓",
  admitted: "✓",
  delayed: "↷",
  decision_needed: "!",
  patient_request: "!",
  confirmed: "▲",
  not_confirmed: "▽",
  unverified: "?",
  escalated: "▲",
  decided: "✓",
  patient_decided: "✓",
  missed: "×",
  finished: "■",
};

export function Feed({
  state,
  limit,
  onOpen,
  onFocus,
}: {
  state: SimState;
  limit?: number;
  onOpen: (subject: Subject) => void;
  onFocus: (org: string) => void;
}) {
  const events = useMemo(() => {
    const visible = [...visibleEvents(state)].reverse();
    return limit ? visible.slice(0, limit) : visible;
  }, [state, limit]);
  const days = useMemo(() => {
    const groups: { day: number; events: SimEvent[] }[] = [];
    for (const e of events) {
      const last = groups.at(-1);
      if (last && last.day === e.day) last.events.push(e);
      else groups.push({ day: e.day, events: [e] });
    }
    return groups;
  }, [events]);
  const origin = state.alerts.filter((a) => (a.lead ?? 99) <= 3).slice(0, 6);
  const subjectOf = (e: SimEvent): Subject | null =>
    e.patientId
      ? { kind: "patient", id: e.patientId }
      : e.alertId
        ? { kind: "alert", id: e.alertId }
        : null;
  return (
    <section
      className="feed"
      aria-label={t.control.feed.title}
      data-tour="feed"
    >
      <header className="feed-head">
        <div>
          <h2>{t.control.feed.title}</h2>
          <p>{t.control.feed.lead}</p>
        </div>
        <span
          className={`feed-clock ${state.playing ? "is-live" : ""}`}
          role="status"
        >
          {state.day === 0
            ? t.control.sim.day(0)
            : t.control.feed.dayClock(clockLabel(state.clock))}
          <i aria-hidden="true" />
        </span>
      </header>
      <ol className="feed-list">
        {days.map((group) => (
          <li key={group.day} className="feed-day">
            <h3 className="feed-day-head">
              {t.control.sim.events.dayHeader(
                group.day,
                fmtDate(addDaysIso(state.origin, group.day)),
              )}
            </h3>
            <ol>
              {group.events.map((e, i) => {
                const subject = subjectOf(e);
                const actionable = ACTIONABLE.has(e.kind);
                const resolved =
                  actionable &&
                  ((e.alertId &&
                    state.alerts.find((a) => a.id === e.alertId)?.decision) ||
                    (e.patientId &&
                      state.patients.find((p) => p.id === e.patientId)
                        ?.status !== "request"));
                return (
                  <li
                    key={e.id}
                    className={`feed-card kind-${e.kind} ${actionable && !resolved ? "needs-you" : ""}`}
                    style={{ animationDelay: `${Math.min(i, 6) * 60}ms` }}
                  >
                    <span className="feed-icon" aria-hidden="true">
                      {ICON[e.kind]}
                    </span>
                    <div className="feed-body">
                      <span className="feed-time">{e.time}</span>
                      {actionable && !resolved ? (
                        <span className="feed-needs">
                          {t.control.feed.needsYou}
                        </span>
                      ) : null}
                      <p className="feed-text">{e.text}</p>
                      {subject ? (
                        <div className="feed-actions">
                          <button
                            type="button"
                            className={
                              actionable && !resolved
                                ? "btn-accent btn-sm"
                                : "btn-ghost btn-sm"
                            }
                            onClick={() => onOpen(subject)}
                          >
                            {t.control.feed.details}
                          </button>
                          {e.org ? (
                            <button
                              type="button"
                              className="btn-link"
                              onClick={() => onFocus(e.org!)}
                            >
                              {t.control.feed.onMap}
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ol>
          </li>
        ))}
        <li className="feed-day feed-origin">
          <h3 className="feed-day-head">
            {t.control.sim.events.originHeader(fmtDate(state.origin))}
          </h3>
          <p className="feed-origin-intro">
            {t.control.sim.events.originIntro(state.alerts.length)}
          </p>
          <ol>
            {origin.map((a, i) => (
              <li
                key={a.id}
                className="feed-card kind-forecast"
                style={{ animationDelay: `${i * 40}ms` }}
              >
                <span className="feed-icon" aria-hidden="true">
                  ◔
                </span>
                <div className="feed-body">
                  <span className="feed-time">{a.hospitalName}</span>
                  <p className="feed-text">
                    {a.profileName} ·{" "}
                    {a.crossing
                      ? t.control.alerts.whenRelative(
                          fmtDate(a.crossing),
                          a.lead ?? 0,
                        )
                      : ""}
                  </p>
                  <div className="feed-actions">
                    <button
                      type="button"
                      className="btn-ghost btn-sm"
                      onClick={() => onOpen({ kind: "alert", id: a.id })}
                    >
                      {t.control.feed.details}
                    </button>
                    <button
                      type="button"
                      className="btn-link"
                      onClick={() => onFocus(a.org)}
                    >
                      {t.control.feed.onMap}
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ol>
          {state.alerts.length > origin.length ? (
            <p className="feed-more">
              {t.control.sim.events.more(state.alerts.length - origin.length)}
            </p>
          ) : null}
        </li>
      </ol>
    </section>
  );
}

function addDaysIso(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
