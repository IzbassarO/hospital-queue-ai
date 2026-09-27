/**
 * Who waits longest at the mart as-of date: hospital × profile rows of the legacy load-index mart ordered by the
 * number of referrals still waiting. It answers the bureau's first question, which the forward-looking inbox cannot:
 * the inbox lists series where the next fourteen days are expected above their own historical level, and a long
 * standing queue is not that. The block is kept apart from the inbox and labelled as a description of what already
 * happened — never a model warning, never a forecast.
 *
 * The API returns the page ordered by its own load index, so the ordering by queue length happens here, over the
 * rows that were read; the footer says how many that was.
 */
import { useMemo } from "react";
import { t } from "../../i18n";
import { useLoadAlerts } from "../../api/queries";
import { fmtDate, fmtNumber } from "../../lib/format";
import { shortenOrganization } from "../../demo/useDemoSubject";
import { useRegionFilter } from "../region";
import { PublishedTag } from "./SyntheticState";

export function QueueFacts({
  asOf,
  limit = 10,
}: {
  asOf: string | null;
  limit?: number;
}) {
  const rows = useLoadAlerts();
  const [region] = useRegionFilter();
  const top = useMemo(() => {
    const items = (rows.data?.items ?? []).filter(
      (r) => (!region || r.region_code === region) && r.queue_now > 0,
    );
    return [...items].sort((a, b) => b.queue_now - a.queue_now).slice(0, limit);
  }, [rows.data, region, limit]);
  return (
    <section
      className="queue-facts panel-block"
      aria-label={t.control.queueFacts.title}
    >
      <header className="block-head">
        <h2>{t.control.queueFacts.title}</h2>
        <p>
          <span className="fact-pill">{t.control.queueFacts.tag}</span>{" "}
          <PublishedTag />{" "}
          {asOf ? t.control.queueFacts.lead(fmtDate(asOf)) : ""}
        </p>
      </header>
      {rows.isError ? (
        <p className="empty">{t.control.queueFacts.unavailable}</p>
      ) : top.length === 0 ? (
        <p className="empty">{t.control.queueFacts.empty}</p>
      ) : (
        <>
          <div className="table-wrap">
            <table className="log-table">
              <thead>
                <tr>
                  <th>{t.control.queueFacts.columns.hospital}</th>
                  <th>{t.control.queueFacts.columns.profile}</th>
                  <th>{t.control.queueFacts.columns.region}</th>
                  <th className="num">{t.control.queueFacts.columns.queue}</th>
                  <th className="num">
                    {t.control.queueFacts.columns.backlog}
                  </th>
                  <th className="num">
                    {t.control.queueFacts.columns.refusal}
                  </th>
                </tr>
              </thead>
              <tbody>
                {top.map((r) => (
                  <tr key={`${r.org_code}:${r.profile_code}`}>
                    <td>{shortenOrganization(r.org_name)}</td>
                    <td>{r.profile_name}</td>
                    <td className="muted">{r.region_name}</td>
                    <td className="num">{fmtNumber(r.queue_now, 0)}</td>
                    <td className="num">
                      {r.backlog_days === null
                        ? "—"
                        : t.control.queue.days(Math.round(r.backlog_days))}
                    </td>
                    <td className="num">
                      {r.refusal_rate_28d === null
                        ? "—"
                        : `${fmtNumber(r.refusal_rate_28d * 100, 1)} %`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="fact-strip-note">
            {t.control.queueFacts.shown(
              top.length,
              rows.data?.items.length ?? 0,
            )}
          </p>
        </>
      )}
    </section>
  );
}
