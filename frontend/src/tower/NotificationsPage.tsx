/** Notifications: the list on the left, the whole picture of the selected one on the right. */
import { useMemo, useState } from "react";
import { t } from "../i18n";
import { fmtDate } from "../lib/format";
import { SeverityPill } from "../demo/primitives";
import { SubjectContent } from "./components/SubjectContent";
import { resolveSubject } from "./subject";
import { pendingTasks } from "./sim/tasks";
import { daysBetween } from "./synthetic";
import type { Subject } from "./ui";
import { useNames, useTowerData, useTowerSimulation } from "./useTowerModel";
import type { TowerModel } from "./useTowerData";

type Filter = "all" | "pending" | "confirmed" | "forecast";

export function NotificationsPage() {
  const { model } = useTowerData();
  if (!model)
    return (
      <div className="scene-state" role="status">
        <span className="pulse" aria-hidden="true" />
        {t.control.loading}
      </div>
    );
  return <Inbox model={model} />;
}

function Inbox({ model }: { model: TowerModel }) {
  const sim = useTowerSimulation(model);
  const { state } = sim;
  const names = useNames(model);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Subject | null>(null);
  const tasks = pendingTasks(state);
  const rows = useMemo(() => {
    const taskRows = tasks.map((task) => ({
      subject: { kind: task.kind, id: task.id } as Subject,
      pending: true,
      alert: task.kind === "alert" ? task.alert : task.alert,
      patient: task.kind === "patient" ? task.patient : undefined,
      order: -1000 + task.order,
    }));
    const alertRows = state.alerts
      .filter(
        (a) => !tasks.some((task) => task.kind === "alert" && task.id === a.id),
      )
      .map((a) => ({
        subject: { kind: "alert", id: a.id } as Subject,
        pending: false,
        alert: a,
        patient: undefined,
        order: (a.phase === "confirmed" ? 0 : 500) + (a.lead ?? 99),
      }));
    return [...taskRows, ...alertRows]
      .filter((r) => {
        if (filter === "pending") return r.pending;
        if (filter === "confirmed") return r.alert?.phase === "confirmed";
        if (filter === "forecast")
          return r.alert?.phase === "forecast" && !r.pending;
        return true;
      })
      .sort((a, b) => a.order - b.order);
  }, [tasks, state.alerts, filter]);
  const current = selected ?? rows[0]?.subject ?? null;
  const view = current ? resolveSubject(current, state, names) : null;
  const filters: Filter[] = ["all", "pending", "confirmed", "forecast"];
  return (
    <>
      <section className="tower-lead">
        <h1>{t.control.pages.notificationsTitle}</h1>
        <p>{t.control.pages.notificationsLead}</p>
      </section>
      <div className="inbox">
        <aside className="inbox-list" aria-label={t.control.alerts.title}>
          <div
            className="queue-filters"
            role="group"
            aria-label={t.control.alerts.title}
          >
            {filters.map((f) => (
              <button
                key={f}
                type="button"
                className={`chip ${filter === f ? "is-active" : ""}`}
                aria-pressed={filter === f}
                onClick={() => setFilter(f)}
              >
                {t.control.feed.filters[f]}
              </button>
            ))}
            <span className="queue-count">
              {t.control.feed.count(rows.length)}
            </span>
          </div>
          <ol className="inbox-rows">
            {rows.map((r) => {
              const active =
                current?.kind === r.subject.kind &&
                current?.id === r.subject.id;
              const alert = r.alert;
              return (
                <li key={`${r.subject.kind}:${r.subject.id}`}>
                  <button
                    type="button"
                    className={`inbox-row ${active ? "is-active" : ""} ${r.pending ? "needs-you" : ""}`}
                    aria-current={active ? "true" : undefined}
                    onClick={() => setSelected(r.subject)}
                  >
                    <span className="inbox-row-top">
                      {alert ? <SeverityPill value={alert.severity} /> : null}
                      <span className="alert-phase">
                        {r.patient
                          ? t.control.explorer.patientTask
                          : alert
                            ? alert.decision
                              ? t.control.alerts.decided(
                                  t.control.decision.actions[
                                    alert.decision.action
                                  ].label,
                                )
                              : t.control.alerts.phase[alert.phase]
                            : ""}
                      </span>
                      {r.pending ? (
                        <span className="feed-needs">
                          {t.control.feed.needsYou}
                        </span>
                      ) : null}
                    </span>
                    <strong className="inbox-row-title">
                      {r.patient
                        ? `${r.patient.id} · ${names.hospital(r.patient.org)}`
                        : alert?.hospitalName}
                    </strong>
                    <span className="inbox-row-meta">
                      {r.patient
                        ? `${names.profile(r.patient.profile)} · ${fmtDate(r.patient.predictedDate)}`
                        : alert
                          ? `${alert.profileName} · ${alert.crossing ? t.control.alerts.whenRelative(fmtDate(alert.crossing), daysBetween(state.date, alert.crossing)) : ""}`
                          : ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </aside>
        <section className="inbox-detail" aria-label={t.control.decision.title}>
          {view ? (
            <SubjectContent
              key={`${view.subject.kind}:${view.subject.id}`}
              view={view}
              state={state}
              onDecideAlert={sim.decide}
              onDecidePatient={sim.decidePatient}
            />
          ) : (
            <p className="empty">{t.control.pages.select}</p>
          )}
        </section>
      </div>
    </>
  );
}
