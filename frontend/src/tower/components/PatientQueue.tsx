/** The queue of expected admissions: pseudonymous synthetic referrals around the published crossing windows. */
import { useMemo, useState } from "react";
import { t } from "../../i18n";
import { fmtDate } from "../../lib/format";
import { addDays } from "../synthetic";
import type { SimPatient } from "../sim/simulation";

type Filter = "all" | "focus" | "soon" | "delayed";

export function PatientQueue({
  patients,
  date,
  focus,
  hospitalName,
  profileName,
  onFocus,
  onOpen,
  pageSize = 10,
}: {
  patients: SimPatient[];
  date: string;
  focus: string | null;
  hospitalName: (org: string) => string;
  profileName: (code: string) => string;
  onFocus: (org: string) => void;
  onOpen?: (id: string) => void;
  pageSize?: number;
}) {
  const PAGE = pageSize;
  const [filter, setFilter] = useState<Filter>("all");
  const [limit, setLimit] = useState(PAGE);
  const active: Filter = filter === "focus" && !focus ? "all" : filter;
  const rows = useMemo(() => {
    const horizon = addDays(date, 3);
    const list = patients.filter((p) => {
      if (active === "focus") return p.org === focus;
      if (active === "soon")
        return (
          p.status !== "admitted" &&
          p.predictedDate >= date &&
          p.predictedDate <= horizon
        );
      if (active === "delayed") return p.status === "delayed";
      return true;
    });
    return list.sort(
      (a, b) =>
        (a.status === "admitted" ? 1 : 0) - (b.status === "admitted" ? 1 : 0) ||
        a.predictedDate.localeCompare(b.predictedDate) ||
        a.id.localeCompare(b.id),
    );
  }, [patients, active, focus, date]);
  const shown = rows.slice(0, limit);
  const filters: Filter[] = ["all", "focus", "soon", "delayed"];
  return (
    <section className="queue" aria-label={t.control.queue.title}>
      <header className="block-head">
        <h2>{t.control.queue.title}</h2>
        <p>{t.control.queue.lead}</p>
      </header>
      <div
        className="queue-filters"
        role="group"
        aria-label={t.control.queue.title}
      >
        {filters.map((f) => (
          <button
            key={f}
            type="button"
            className={`chip ${active === f ? "is-active" : ""}`}
            aria-pressed={active === f}
            disabled={f === "focus" && !focus}
            onClick={() => {
              setFilter(f);
              setLimit(PAGE);
            }}
          >
            {t.control.queue.filters[f]}
          </button>
        ))}
        <span className="queue-count">
          {t.control.queue.total(shown.length, rows.length)}
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="empty">{t.control.queue.empty}</p>
      ) : (
        <div className="table-wrap">
          <table className="queue-table">
            <thead>
              <tr>
                <th>{t.control.queue.columns.id}</th>
                <th>
                  {t.control.queue.columns.hospital} ·{" "}
                  {t.control.queue.columns.profile.toLowerCase()}
                </th>
                <th>{t.control.queue.columns.expected}</th>
                <th className="num">{t.control.queue.columns.wait}</th>
                <th>{t.control.queue.columns.urgency}</th>
                <th>{t.control.queue.columns.status}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr
                  key={p.id}
                  className={`status-${p.status} ${p.org === focus ? "is-focus" : ""}`}
                >
                  <td className="mono">
                    {onOpen ? (
                      <button
                        type="button"
                        className="cell-link"
                        onClick={() => onOpen(p.id)}
                      >
                        {p.id}
                      </button>
                    ) : (
                      p.id
                    )}
                  </td>
                  <td className="cell-subject">
                    <button
                      type="button"
                      className="cell-link"
                      onClick={() => onFocus(p.org)}
                    >
                      {hospitalName(p.org)}
                    </button>
                    <span
                      className="cell-profile"
                      title={profileName(p.profile)}
                    >
                      {profileName(p.profile)}
                    </span>
                  </td>
                  <td>
                    <strong>
                      {fmtDate(p.admittedDate ?? p.predictedDate)}
                    </strong>
                  </td>
                  <td className="num">
                    {t.control.queue.days(p.predictedWait)}
                  </td>
                  <td>
                    <span className={`urgency-dot is-${p.urgency}`} />
                    {t.control.urgency[p.urgency]}
                  </td>
                  <td>
                    <span className={`queue-status is-${p.status}`}>
                      {t.control.queue.status[p.status]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > limit ? (
        <button
          type="button"
          className="btn-ghost btn-sm"
          onClick={() => setLimit((l) => l + PAGE)}
        >
          {t.control.queue.more(rows.length - limit)}
        </button>
      ) : null}
    </section>
  );
}
