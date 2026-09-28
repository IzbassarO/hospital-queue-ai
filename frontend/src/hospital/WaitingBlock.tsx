/**
 * "Кто ждёт" — the measured queue at the origin: totals, the share of each bed profile, how long people have
 * already waited, and the referrals themselves.
 *
 * The table is a column list, not a fixed layout: `columns()` returns descriptors and the markup maps over them.
 * When per-referral estimates are published (wait, refusal, journey), each becomes one more entry in that array —
 * no new table and no reflow of the existing cells. Until then nothing is shown in their place: an empty column
 * promising a number the product does not have is worse than no column.
 */
import { useState } from "react";
import { t } from "../i18n";
import { fmtDate, fmtNumber } from "../lib/format";
import {
  useWaitingReferrals,
  type ReferralOrder,
  type WaitingHospitalDetail,
  type WaitingReferral,
} from "../api/waiting-list";

const PAGE = 25;

interface Column {
  key: string;
  label: string;
  className?: string;
  /** dropped on a phone, where only the referral, its wait and its outcome fit */
  secondary?: boolean;
  render: (row: WaitingReferral) => React.ReactNode;
}

/** Columns of the queue table, in order. Adding a published per-referral estimate means adding one entry here. */
function columns(origin: string): Column[] {
  return [
    {
      key: "code",
      label: t.hospital.waiting.table.code,
      className: "is-code",
      render: (row) => (
        <>
          {row.hospitalization_code}
          {row.is_duplicate_code ? (
            <em
              className="hos-dup"
              title={t.hospital.waiting.table.duplicate}
              aria-label={t.hospital.waiting.table.duplicate}
            >
              ×2
            </em>
          ) : null}
        </>
      ),
    },
    {
      key: "profile",
      label: t.hospital.waiting.table.profile,
      secondary: true,
      render: (row) => row.profile_name,
    },
    {
      key: "registered",
      label: t.hospital.waiting.table.registered,
      className: "is-num",
      secondary: true,
      render: (row) => fmtDate(row.registration_date),
    },
    {
      key: "waited",
      label: t.hospital.waiting.table.waited,
      className: "is-num",
      render: (row) => fmtNumber(row.days_waited_at_origin, 0),
    },
    {
      key: "outcome",
      label: t.hospital.waiting.table.outcome,
      className: "is-hindsight",
      render: (row) => {
        const observed = row.observed_after_origin;
        return (
          <>
            <span className={`hos-outcome is-${observed.status.toLowerCase()}`}>
              {t.hospital.waiting.outcome[observed.status]}
            </span>
            {observed.event_date && observed.days_from_origin != null ? (
              <small>
                {t.hospital.waiting.outcome.on(
                  fmtDate(observed.event_date),
                  observed.days_from_origin,
                )}
              </small>
            ) : (
              <small>{t.hospital.hindsight.short(fmtDate(origin))}</small>
            )}
          </>
        );
      },
    },
  ];
}

function ProfileBars({ detail }: { detail: WaitingHospitalDetail }) {
  const largest = Math.max(1, ...detail.profiles.map((p) => p.waiting_count));
  return (
    <div className="hos-sub">
      <h3>{t.hospital.waiting.byProfile}</h3>
      <p className="hos-sub-hint">{t.hospital.waiting.byProfileHint}</p>
      <ul className="hos-bars" role="list">
        {detail.profiles.slice(0, 8).map((p) => (
          <li key={p.profile_code}>
            <span className="hos-bar-label" title={p.profile_name}>
              {p.profile_name}
            </span>
            <span className="hos-bar-track" aria-hidden="true">
              <span
                className="hos-bar-fill"
                style={{ width: `${(p.waiting_count / largest) * 100}%` }}
              />
            </span>
            <span className="hos-bar-value">
              {fmtNumber(p.waiting_count, 0)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DaysHistogram({ detail }: { detail: WaitingHospitalDetail }) {
  const largest = Math.max(
    1,
    ...detail.days_waited_histogram.map((b) => b.count),
  );
  return (
    <div className="hos-sub">
      <h3>{t.hospital.waiting.histogram}</h3>
      <p className="hos-sub-hint">{t.hospital.waiting.histogramHint}</p>
      <ol className="hos-hist" role="list">
        {detail.days_waited_histogram.map((b) => (
          <li key={b.from_days}>
            <span className="hos-hist-bar" aria-hidden="true">
              <span
                style={{ height: `${Math.max(3, (b.count / largest) * 100)}%` }}
              />
            </span>
            <span className="hos-hist-count">{fmtNumber(b.count, 0)}</span>
            <span className="hos-hist-label">
              {t.hospital.waiting.bucket(b.from_days, b.to_days)}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function WaitingBlock({
  detail,
  profile,
}: {
  detail: WaitingHospitalDetail;
  profile: string | null;
}) {
  const [order, setOrder] = useState<ReferralOrder>("longest_wait");
  const [page, setPage] = useState(0);
  const [scoped, setScoped] = useState(false);
  const query = {
    profile: scoped ? profile : null,
    order,
    limit: PAGE,
    offset: page * PAGE,
  };
  const referrals = useWaitingReferrals(detail.org_code, query);
  const rows = referrals.data?.items ?? [];
  const total = referrals.data?.total ?? 0;
  const cols = columns(detail.origin);
  const setOrderAndReset = (next: ReferralOrder) => {
    setOrder(next);
    setPage(0);
  };

  return (
    <section className="hos-block" aria-label={t.hospital.waiting.title}>
      <div className="block-head">
        <h2>{t.hospital.waiting.title}</h2>
        <p>{t.hospital.waiting.subtitle(fmtDate(detail.origin))}</p>
      </div>
      <dl className="hos-totals">
        <div>
          <dd>{fmtNumber(detail.waiting_count, 0)}</dd>
          <dt>{t.hospital.waiting.totals.waiting}</dt>
        </div>
        <div>
          <dd>{fmtNumber(detail.profile_count, 0)}</dd>
          <dt>{t.hospital.waiting.totals.profiles}</dt>
        </div>
        <div>
          <dd>{fmtNumber(detail.median_days_waited, 0)}</dd>
          <dt>{t.hospital.waiting.totals.median}</dt>
        </div>
        <div>
          <dd>{fmtNumber(detail.max_days_waited, 0)}</dd>
          <dt>{t.hospital.waiting.totals.longest}</dt>
        </div>
      </dl>
      <div className="hos-split">
        <ProfileBars detail={detail} />
        <DaysHistogram detail={detail} />
      </div>

      <div className="hos-table-head">
        <h3>{t.hospital.waiting.table.title}</h3>
        <div className="hos-table-controls">
          {profile ? (
            <label className="hos-check">
              <input
                type="checkbox"
                checked={scoped}
                onChange={(e) => {
                  setScoped(e.target.checked);
                  setPage(0);
                }}
              />
              <span>
                {scoped ? profile : t.hospital.waiting.table.allProfiles}
              </span>
            </label>
          ) : null}
          <div className="hos-segment" role="group">
            <button
              type="button"
              className={order === "longest_wait" ? "is-on" : ""}
              aria-pressed={order === "longest_wait"}
              onClick={() => setOrderAndReset("longest_wait")}
            >
              {t.hospital.waiting.table.sortLongest}
            </button>
            <button
              type="button"
              className={order === "shortest_wait" ? "is-on" : ""}
              aria-pressed={order === "shortest_wait"}
              onClick={() => setOrderAndReset("shortest_wait")}
            >
              {t.hospital.waiting.table.sortShortest}
            </button>
          </div>
        </div>
      </div>
      <p className="hos-note">{t.hospital.waiting.table.noPredictions}</p>
      <div className="hos-table-scroll">
        <table className="hos-table">
          <thead>
            <tr>
              {cols.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className={[c.className, c.secondary ? "is-secondary" : ""]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {c.key === "outcome" ? (
                    <>
                      {c.label}{" "}
                      <em className="hos-hindsight-tag">
                        {t.hospital.hindsight.tag}
                      </em>
                    </>
                  ) : (
                    c.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.referral_id}>
                {cols.map((c) => (
                  <td
                    key={c.key}
                    className={[c.className, c.secondary ? "is-secondary" : ""]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="hos-pager">
        <button
          type="button"
          className="btn-sm"
          disabled={page === 0}
          onClick={() => setPage((p) => Math.max(0, p - 1))}
        >
          {t.hospital.waiting.table.prev}
        </button>
        <span role="status">
          {t.hospital.waiting.table.page(
            total === 0 ? 0 : page * PAGE + 1,
            Math.min(total, (page + 1) * PAGE),
            total,
          )}
        </span>
        <button
          type="button"
          className="btn-sm"
          disabled={(page + 1) * PAGE >= total}
          onClick={() => setPage((p) => p + 1)}
        >
          {t.hospital.waiting.table.next}
        </button>
      </div>
    </section>
  );
}
