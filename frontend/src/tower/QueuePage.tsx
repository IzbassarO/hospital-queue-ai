/**
 * The full synthetic queue, thirty days deep, with the decision journal underneath. With the synthetic layer off
 * the queue is an explicit empty state; the journal of decisions on published notifications stays. The real queue of
 * the data mart sits next to the synthetic counters (FactStrip) so the two are never read as one number, and both
 * CSV downloads carry a `#` line saying what the rows are; the queue file is named `synthetic-queue-…` and every row
 * repeats the source in its own column.
 */
import { t } from "../i18n";
import { fmtDate } from "../lib/format";
import { FactStrip } from "./components/FactStrip";
import { PatientQueue } from "./components/PatientQueue";
import { SyntheticTag } from "./components/SyntheticState";
import { downloadCsv, toCsv } from "./export";
import { WaitingStrip } from "./components/WaitingStrip";
import { SYNTHETIC_ENABLED } from "./synthetic";
import { openSubject } from "./ui";
import { useNames, useTowerData, useTowerSimulation } from "./useTowerModel";
import type { TowerModel } from "./useTowerData";

export function QueuePage() {
  const { model } = useTowerData();
  if (!model)
    return (
      <div className="scene-state" role="status">
        <span className="pulse" aria-hidden="true" />
        {t.control.loading}
      </div>
    );
  return <QueueBoard model={model} />;
}

function QueueBoard({ model }: { model: TowerModel }) {
  const { state } = useTowerSimulation(model);
  const names = useNames(model);
  return (
    <>
      <section className="tower-lead">
        <h1>{t.control.pages.queueTitle}</h1>
        <p>
          {SYNTHETIC_ENABLED
            ? t.control.pages.queueLead
            : t.control.syntheticOff.queue}
        </p>
        <div className="export-row">
          <button
            type="button"
            className="btn-ghost btn-sm"
            hidden={!SYNTHETIC_ENABLED}
            onClick={() =>
              downloadCsv(
                `synthetic-queue-${state.date}.csv`,
                toCsv(
                  [
                    t.control.queue.columns.id,
                    t.control.queue.columns.hospital,
                    t.control.queue.columns.profile,
                    t.control.queue.columns.referred,
                    t.control.queue.columns.expected,
                    t.control.queue.columns.wait,
                    t.control.queue.columns.urgency,
                    t.control.queue.columns.status,
                    t.control.exportCsv.sourceColumn,
                  ],
                  state.patients.map((p) => [
                    p.id,
                    names.hospital(p.org),
                    names.profile(p.profile),
                    fmtDate(p.referralDate),
                    fmtDate(p.admittedDate ?? p.predictedDate),
                    p.predictedWait,
                    t.control.urgency[p.urgency],
                    t.control.queue.status[p.status],
                    t.control.exportCsv.sourceSynthetic,
                  ]),
                  [t.control.exportCsv.syntheticNote(fmtDate(model.origin))],
                ),
              )
            }
          >
            {t.control.exportCsv.queue}
          </button>
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={() =>
              downloadCsv(
                `decisions-${state.date}.csv`,
                toCsv(
                  [
                    t.control.decision.columns.day,
                    t.control.decision.columns.subject,
                    t.control.decision.columns.action,
                    t.control.decision.columns.comment,
                  ],
                  [
                    ...state.alerts
                      .filter((a) => a.decision)
                      .map((a) => [
                        a.decision!.day,
                        `${a.hospitalName} · ${a.profileName}`,
                        t.control.decision.actions[a.decision!.action].label,
                        a.decision!.comment,
                      ]),
                    ...state.patients
                      .filter((p) => p.decision)
                      .map((p) => [
                        p.decision!.day,
                        `${p.id} · ${names.hospital(p.org)} · ${names.profile(p.profile)}`,
                        t.control.patientDecision.actions[p.decision!.action]
                          .label,
                        p.decision!.comment,
                      ]),
                  ],
                  [t.control.exportCsv.decisionsNote(fmtDate(model.origin))],
                ),
              )
            }
          >
            {t.control.exportCsv.decisions}
          </button>
        </div>
      </section>
      <div className="waiting-row">
        <WaitingStrip state={state} />
        <FactStrip regionName={model.regionName} />
      </div>
      {SYNTHETIC_ENABLED ? (
        <PatientQueue
          patients={state.patients}
          date={state.date}
          focus={null}
          hospitalName={names.hospital}
          profileName={names.profile}
          onFocus={() => undefined}
          onOpen={(id) => openSubject({ kind: "patient", id })}
          pageSize={25}
        />
      ) : (
        <section
          className="queue queue-off panel-block"
          role="status"
          aria-label={t.control.queue.title}
        >
          <header className="block-head">
            <h2>{t.control.queue.title}</h2>
            <p>
              {t.control.syntheticOff.title} <SyntheticTag />
            </p>
          </header>
          <p className="empty">{t.control.syntheticOff.queue}</p>
        </section>
      )}
      <Journal state={state} names={names} />
    </>
  );
}

import type { SimState } from "./sim/simulation";
function Journal({
  state,
  names,
}: {
  state: SimState;
  names: {
    hospital: (org: string) => string;
    profile: (code: string) => string;
  };
}) {
  const rows = [
    ...state.alerts
      .filter((a) => a.decision)
      .map((a) => ({
        key: `a:${a.id}`,
        day: a.decision!.day,
        subject: `${a.hospitalName} · ${a.profileName}`,
        action: t.control.decision.actions[a.decision!.action].label,
        comment: a.decision!.comment,
        open: () => openSubject({ kind: "alert", id: a.id }),
      })),
    ...state.patients
      .filter((p) => p.decision)
      .map((p) => ({
        key: `p:${p.id}`,
        day: p.decision!.day,
        subject: `${p.id} · ${names.hospital(p.org)} · ${names.profile(p.profile)}`,
        action: t.control.patientDecision.actions[p.decision!.action].label,
        comment: p.decision!.comment,
        open: () => openSubject({ kind: "patient", id: p.id }),
      })),
  ].sort((a, b) => b.day - a.day || a.subject.localeCompare(b.subject));
  return (
    <section
      className="journal-decisions panel-block"
      aria-label={t.control.decision.logTitle}
    >
      <header className="block-head">
        <h2>{t.control.decision.logTitle}</h2>
      </header>
      {rows.length === 0 ? (
        <p className="empty">{t.control.decision.logEmpty}</p>
      ) : (
        <div className="table-wrap">
          <table className="log-table">
            <thead>
              <tr>
                <th className="num">{t.control.decision.columns.day}</th>
                <th>{t.control.decision.columns.subject}</th>
                <th>{t.control.decision.columns.action}</th>
                <th>{t.control.decision.columns.comment}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="num">{r.day}</td>
                  <td>
                    <button
                      type="button"
                      className="cell-link"
                      onClick={r.open}
                    >
                      {r.subject}
                    </button>
                  </td>
                  <td>{r.action}</td>
                  <td className="muted">{r.comment || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
