/** Top of the specialist's inbox on the main page; the full list lives on the notifications page. */
import { Link } from "react-router-dom";
import { t } from "../../i18n";
import { fmtDate } from "../../lib/format";
import { SeverityPill } from "../../demo/primitives";
import { pendingTasks } from "../sim/tasks";
import type { SimState } from "../sim/simulation";
import { openSubject } from "../ui";

export function PriorityList({
  state,
  names,
  limit = 5,
}: {
  state: SimState;
  names: {
    hospital: (org: string) => string;
    profile: (code: string) => string;
  };
  limit?: number;
}) {
  const tasks = pendingTasks(state);
  return (
    <section className="priority" aria-label={t.control.priority.title}>
      <header className="block-head block-head-row">
        <div>
          <h2>{t.control.priority.title}</h2>
          <p>{t.control.priority.lead}</p>
        </div>
        <Link to="/notifications" className="btn-ghost btn-sm">
          {t.control.priority.all}
        </Link>
      </header>
      {tasks.length === 0 ? (
        <p className="empty">{t.control.priority.empty}</p>
      ) : (
        <ol className="task-list">
          {tasks.slice(0, limit).map((task, i) => (
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
                onClick={() => openSubject({ kind: task.kind, id: task.id })}
              >
                {t.control.explorer.open}
              </button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
