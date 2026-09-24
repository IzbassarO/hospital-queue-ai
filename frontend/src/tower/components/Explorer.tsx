/** The task drawer: every open request in arrival order, on every page. */
import { t } from "../../i18n";
import { pendingTasks } from "../sim/tasks";
import type { SimState } from "../sim/simulation";
import { SeverityPill } from "../../demo/primitives";
import { fmtDate } from "../../lib/format";
import { closeExplorer, openSubject } from "../ui";

export function Explorer({
  state,
  open,
  names,
}: {
  state: SimState | null;
  open: boolean;
  names: {
    hospital: (org: string) => string;
    profile: (code: string) => string;
  };
}) {
  const tasks = state ? pendingTasks(state) : [];
  const doneToday = state
    ? state.events.filter(
        (e) =>
          e.day === state.day &&
          (e.kind === "decided" || e.kind === "patient_decided"),
      ).length
    : 0;
  return (
    <aside
      className={`explorer ${open ? "is-open" : ""}`}
      aria-label={t.control.explorer.title}
      aria-hidden={!open}
    >
      <header className="explorer-head">
        <div>
          <h2>{t.control.explorer.title}</h2>
          <p>{t.control.explorer.lead}</p>
        </div>
        <button
          type="button"
          className="dialog-close"
          aria-label={t.control.decision.close}
          onClick={closeExplorer}
        >
          ×
        </button>
      </header>
      {!state ? (
        <p className="empty">{t.control.explorer.notStarted}</p>
      ) : tasks.length === 0 ? (
        <p className="empty">{t.control.explorer.empty}</p>
      ) : (
        <ol className="task-list">
          {tasks.map((task, i) => (
            <li
              key={`${task.kind}:${task.id}`}
              className={`task is-${task.urgency}`}
            >
              <span className="task-index">{i + 1}</span>
              <div className="task-body">
                <span className="task-kind">
                  {task.kind === "alert"
                    ? t.control.explorer.alertTask
                    : t.control.explorer.patientTask}
                  {" · "}
                  {t.control.explorer.since(task.day, task.time)}
                </span>
                <strong className="task-title">
                  {task.kind === "alert"
                    ? task.alert.hospitalName
                    : `${task.patient.id} · ${names.hospital(task.patient.org)}`}
                </strong>
                <span className="task-meta">
                  {task.kind === "alert"
                    ? task.alert.profileName
                    : `${names.profile(task.patient.profile)} · ${fmtDate(task.patient.predictedDate)}`}
                </span>
                <span className="task-tags">
                  {task.kind === "alert" ? (
                    <SeverityPill value={task.alert.severity} />
                  ) : null}
                  <span className={`alert-urgency is-${task.urgency}`}>
                    {t.control.urgency[task.urgency]}
                  </span>
                </span>
              </div>
              <button
                type="button"
                className="btn-accent btn-sm"
                onClick={() => {
                  openSubject({ kind: task.kind, id: task.id });
                }}
              >
                {t.control.explorer.open}
              </button>
            </li>
          ))}
        </ol>
      )}
      {state ? (
        <p className="explorer-foot">{t.control.explorer.done(doneToday)}</p>
      ) : null}
    </aside>
  );
}
