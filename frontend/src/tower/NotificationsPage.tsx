/**
 * Notifications: the list on the left, the whole picture of the selected one on the right. The list is the shown
 * part of the attention queue and says so; a "my region" filter, remembered in the browser, narrows it to the
 * oblast a bureau specialist works in. An API failure is a message with a retry, never a spinner.
 *
 * Two facets shape the list without touching published values. The profile facet defaults to "without the day
 * hospital": day-hospital series dominate the publication by count and a bureau specialist looks for inpatient
 * profiles first; both halves keep a visible count so nothing is hidden silently. The order chips re-sort the same
 * rows — by the published rank (default, the publication\'s own order), by the queue at the mart as-of date or by
 * the historical median wait, both from the hospital-card facts already fetched for the verdict.
 *
 * Under the inbox sits a separate, clearly labelled descriptive block (QueueFacts): the longest queues at the mart
 * as-of date. It is a fact list, not a forecast and not a model warning.
 */
import { useMemo, useState } from "react";
import { t } from "../i18n";
import { daysBetween } from "../lib/dates";
import { fmtDate, fmtNumber } from "../lib/format";
import { SeverityPill } from "../demo/primitives";
import { QueueFacts } from "./components/QueueFacts";
import { RegionFilter } from "./components/RegionFilter";
import { useRegionFilter } from "./region";
import { RegistryNote } from "./components/RegistryNote";
import { SubjectContent } from "./components/SubjectContent";
import { TowerError } from "./components/TowerError";
import { resolveSubject } from "./subject";
import { pendingTasks } from "./sim/tasks";
import type { Subject } from "./ui";
import { useNames, useTowerData, useTowerSimulation } from "./useTowerModel";
import type { TowerModel } from "./useTowerData";

type Filter = "all" | "pending" | "confirmed" | "forecast";
type ProfileFacet = "withoutDayHospital" | "dayHospitalOnly" | "allProfiles";
type Order = "byRank" | "byQueue" | "byWait";

const PROFILE_FACETS: ProfileFacet[] = [
  "withoutDayHospital",
  "dayHospitalOnly",
  "allProfiles",
];
const ORDERS: Order[] = ["byRank", "byQueue", "byWait"];

export function NotificationsPage() {
  const { model, error, refetch } = useTowerData();
  if (!model && error) return <TowerError error={error} onRetry={refetch} />;
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
  const [facet, setFacet] = useState<ProfileFacet>("withoutDayHospital");
  const [order, setOrder] = useState<Order>("byRank");
  const [region] = useRegionFilter();
  const [selected, setSelected] = useState<Subject | null>(null);
  const tasks = pendingTasks(state);
  const dayHospital = model.dayHospitalProfiles;
  const scoped = useMemo(() => {
    const taskRows = tasks.map((task) => ({
      subject: { kind: task.kind, id: task.id } as Subject,
      pending: true,
      alert: task.kind === "alert" ? task.alert : task.alert,
      patient: task.kind === "patient" ? task.patient : undefined,
      region: task.kind === "alert" ? task.alert.region : task.patient.region,
      profile:
        task.kind === "alert" ? task.alert.profile : task.patient.profile,
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
        region: a.region,
        profile: a.profile,
        order: (a.phase === "confirmed" ? 0 : 500) + (a.lead ?? 99),
      }));
    return [...taskRows, ...alertRows]
      .filter((r) => !region || r.region === region)
      .filter((r) => {
        if (filter === "pending") return r.pending;
        if (filter === "confirmed") return r.alert?.phase === "confirmed";
        if (filter === "forecast")
          return r.alert?.phase === "forecast" && !r.pending;
        return true;
      });
  }, [tasks, state.alerts, filter, region]);
  const facetCounts = useMemo(
    () => ({
      withoutDayHospital: scoped.filter((r) => !dayHospital.has(r.profile))
        .length,
      dayHospitalOnly: scoped.filter((r) => dayHospital.has(r.profile)).length,
      allProfiles: scoped.length,
    }),
    [scoped, dayHospital],
  );
  const rows = useMemo(() => {
    const inFacet = scoped.filter((r) =>
      facet === "allProfiles"
        ? true
        : facet === "dayHospitalOnly"
          ? dayHospital.has(r.profile)
          : !dayHospital.has(r.profile),
    );
    // A row without the fact the order asks for goes last; ties keep the published order.
    const key = (r: (typeof inFacet)[number]) =>
      order === "byQueue"
        ? (r.alert?.queueNow ?? -1)
        : (r.alert?.medianWait ?? -1);
    return order === "byRank"
      ? [...inFacet].sort((a, b) => a.order - b.order)
      : [...inFacet].sort((a, b) => key(b) - key(a) || a.order - b.order);
  }, [scoped, facet, order, dayHospital]);
  const current = selected ?? rows[0]?.subject ?? null;
  const view = current ? resolveSubject(current, state, names) : null;
  const filters: Filter[] = ["all", "pending", "confirmed", "forecast"];
  return (
    <>
      <section className="tower-lead">
        <h1>{t.control.pages.notificationsTitle}</h1>
        <p>
          {t.control.pages.notificationsLead}{" "}
          {t.control.pages.notificationsShown(
            state.alerts.length,
            fmtNumber(model.counts.attention, 0),
          )}{" "}
          <RegistryNote />
        </p>
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
            <RegionFilter regions={model.regions} />
            <span className="queue-count">
              {t.control.feed.count(rows.length)}
            </span>
          </div>
          <div
            className="queue-filters"
            role="group"
            aria-label={t.control.facet.profileLabel}
          >
            <span className="facet-label">{t.control.facet.profileLabel}</span>
            {PROFILE_FACETS.map((f) => (
              <button
                key={f}
                type="button"
                className={`chip ${facet === f ? "is-active" : ""}`}
                aria-pressed={facet === f}
                onClick={() => setFacet(f)}
              >
                {t.control.facet[f]} · {facetCounts[f]}
              </button>
            ))}
          </div>
          <div
            className="queue-filters"
            role="group"
            aria-label={t.control.facet.sortLabel}
          >
            <span className="facet-label">{t.control.facet.sortLabel}</span>
            {ORDERS.map((o) => (
              <button
                key={o}
                type="button"
                className={`chip ${order === o ? "is-active" : ""}`}
                aria-pressed={order === o}
                title={t.control.facet.sortHint[o]}
                onClick={() => setOrder(o)}
              >
                {t.control.facet[o]}
              </button>
            ))}
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
            {rows.length === 0 ? (
              <li className="empty">{t.control.alerts.empty}</li>
            ) : null}
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
      <QueueFacts asOf={model.martAsOf} />
    </>
  );
}
