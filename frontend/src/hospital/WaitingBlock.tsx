/**
 * "Кто ждёт" — the measured queue at the origin: totals, the share of each bed profile, how long people have
 * already waited, and the referrals themselves, each with the estimate the model could make on the origin day.
 *
 * Rendered as the first tab of QueueSection, which owns the <section> and its label.
 *
 * The table is a column list, not a fixed layout: `columns()` returns descriptors and the markup maps over them.
 * The estimate columns are appended only when an estimate publication stands at the queue's origin — an empty
 * column promising a number the product does not have is worse than no column — and a single row without an
 * estimate says so in words rather than showing a blank or a zero.
 *
 * Two publications meet on every row and the screen never lets them blur: the outcome column is hindsight and
 * carries the "ретроспектива" tag, the estimate columns are origin-time and carry the model's name and the
 * evidence tier the curve came from.
 *
 * `degenerate_30d` is why the sub-line of the two probability cells is not decoration. The served curve is
 * conditional on the wait already served, so for a referral that has waited eleven weeks the comparable history
 * still at risk is thin, and the whole 30-day mass collapses onto one outcome. The default order of this table is
 * the longest wait, which lands on exactly those rows: printing a bare "0%" there would be the most confident
 * number on the screen and the least supported. The publication flags them and the cell says so in words.
 */
import { useState } from "react";
import { t } from "../i18n";
import { fmtDate, fmtDays, fmtNumber, fmtPercent } from "../lib/format";
import {
  useQueueReferrals,
  type QueueOrder,
  type QueueReferral,
  type ReferralEstimate,
  type ReferralEstimatesPublication,
} from "../api/referral-estimates";
import type { WaitingHospitalDetail } from "../api/waiting-list";

const PAGE = 25;
const ESTIMATE_HORIZONS = [7, 14, 30] as const;

interface Column {
  key: string;
  label: string;
  className?: string;
  /** dropped on a phone, where only the referral, its wait, its two headline numbers and its outcome fit */
  secondary?: boolean;
  render: (row: QueueReferral) => React.ReactNode;
}

function NoEstimate() {
  return (
    <span className="hos-noestimate" title={t.hospital.estimates.noneHint}>
      {t.hospital.estimates.none}
    </span>
  );
}

/** Says in words that a collapsed 30-day distribution is an absence of comparable outcomes, not a certainty. */
function Degenerate({
  publication,
}: {
  publication: ReferralEstimatesPublication;
}) {
  return (
    <small className="hos-degenerate" title={publication.degeneracy.definition}>
      {t.hospital.estimates.degenerate.short}
    </small>
  );
}

/** P(admitted) at each published horizon. The headline is day 14; 7 and 30 sit under it and drop on a phone. */
function AdmittedCell({
  estimate,
  publication,
}: {
  estimate: ReferralEstimate;
  publication: ReferralEstimatesPublication;
}) {
  return (
    <>
      <b className="hos-est-head">{fmtPercent(estimate.admitted_14d, 0)}</b>
      {estimate.degenerate_30d ? (
        <Degenerate publication={publication} />
      ) : (
        <small>
          {ESTIMATE_HORIZONS.filter((h) => h !== 14)
            .map(
              (h) =>
                `${t.hospital.estimates.byDay(h)} ${fmtPercent(
                  h === 7 ? estimate.admitted_7d : estimate.admitted_30d,
                  0,
                )}`,
            )
            .join(" · ")}
        </small>
      )}
    </>
  );
}

function RefusedCell({
  estimate,
  publication,
}: {
  estimate: ReferralEstimate;
  publication: ReferralEstimatesPublication;
}) {
  return (
    <>
      <b
        className={
          estimate.refusal_attention ? "hos-est-head is-flag" : "hos-est-head"
        }
      >
        {fmtPercent(estimate.refused_30d, 0)}
      </b>
      {estimate.refusal_attention ? (
        <em className="hos-flag">{t.hospital.estimates.attention.tag}</em>
      ) : null}
      {estimate.degenerate_30d ? (
        <Degenerate publication={publication} />
      ) : (
        <small>
          {t.hospital.estimates.stillWaiting(
            fmtPercent(estimate.still_waiting_30d, 0),
          )}
        </small>
      )}
    </>
  );
}

function WindowCell({ estimate }: { estimate: ReferralEstimate }) {
  if (estimate.abstention_reason !== null)
    return (
      <span
        className="hos-abstain"
        title={t.hospital.estimates.window.abstain[estimate.abstention_reason]}
      >
        {t.hospital.estimates.window.abstainShort}
      </span>
    );
  return (
    <>
      {t.hospital.estimates.window.range(
        fmtDays(estimate.window_lower_days, 1),
        fmtDays(estimate.window_upper_days, 1),
      )}
      <small>
        {t.hospital.estimates.window.coverage(
          fmtPercent(estimate.window_coverage, 0),
        )}
      </small>
    </>
  );
}

function TierCell({ estimate }: { estimate: ReferralEstimate }) {
  return (
    <>
      <span className={`hos-tier is-${estimate.estimate_tier}`}>
        {t.hospital.estimates.tier[estimate.estimate_tier]}
      </span>
      {estimate.estimate_tier === "hospital_profile" ? (
        <small>
          {t.hospital.estimates.tierRows(estimate.similar_training_rows)}
        </small>
      ) : null}
    </>
  );
}

/** Columns of the queue table, in order. The estimate columns exist only while an estimate publication does. */
function columns(
  origin: string,
  publication: ReferralEstimatesPublication | null,
): Column[] {
  const measured: Column[] = [
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
  ];

  const estimates: Column[] = [
    {
      key: "admitted",
      label: t.hospital.estimates.columns.admitted,
      className: "is-num is-estimate",
      render: (row) =>
        row.estimate && publication ? (
          <AdmittedCell estimate={row.estimate} publication={publication} />
        ) : (
          <NoEstimate />
        ),
    },
    {
      key: "refused",
      label: t.hospital.estimates.columns.refused,
      className: "is-num is-estimate",
      render: (row) =>
        row.estimate && publication ? (
          <RefusedCell estimate={row.estimate} publication={publication} />
        ) : (
          <NoEstimate />
        ),
    },
    {
      key: "window",
      label: t.hospital.estimates.columns.window,
      className: "is-estimate",
      secondary: true,
      render: (row) =>
        row.estimate ? <WindowCell estimate={row.estimate} /> : <NoEstimate />,
    },
    {
      key: "tier",
      label: t.hospital.estimates.columns.tier,
      className: "is-estimate",
      secondary: true,
      render: (row) =>
        row.estimate ? <TierCell estimate={row.estimate} /> : <NoEstimate />,
    },
  ];

  const outcome: Column = {
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
  };

  return publication
    ? [...measured, ...estimates, outcome]
    : [...measured, outcome];
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
  estimates,
}: {
  detail: WaitingHospitalDetail;
  profile: string | null;
  estimates: ReferralEstimatesPublication | null;
}) {
  const [order, setOrder] = useState<QueueOrder>("longest_wait");
  const [page, setPage] = useState(0);
  const [scoped, setScoped] = useState(false);
  const [attention, setAttention] = useState(false);
  // The estimates only line up with this queue when both publications stand at the same origin; the API says so
  // rather than the UI guessing, and without that the table stays the measured queue it always was.
  const joined = estimates?.matches_waiting_list ? estimates : null;
  const query = {
    profile: scoped ? profile : null,
    order,
    attention: Boolean(joined) && attention,
    limit: PAGE,
    offset: page * PAGE,
  };
  const referrals = useQueueReferrals(detail.org_code, query);
  const rows = referrals.data?.items ?? [];
  const total = referrals.data?.total ?? 0;
  const cols = columns(detail.origin, joined);
  const reset = () => setPage(0);
  const setOrderAndReset = (next: QueueOrder) => {
    setOrder(next);
    reset();
  };
  const modelName = joined
    ? t.hospital.why.models[joined.selection.selected_model]
    : "";

  return (
    <div className="hos-queue">
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
                  reset();
                }}
              />
              <span>
                {scoped ? profile : t.hospital.waiting.table.allProfiles}
              </span>
            </label>
          ) : null}
          {joined ? (
            <label className="hos-check">
              <input
                type="checkbox"
                checked={attention}
                onChange={(e) => {
                  setAttention(e.target.checked);
                  reset();
                }}
              />
              <span>{t.hospital.estimates.attention.filter}</span>
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
            {joined ? (
              <button
                type="button"
                className={order === "highest_refusal_risk" ? "is-on" : ""}
                aria-pressed={order === "highest_refusal_risk"}
                onClick={() => setOrderAndReset("highest_refusal_risk")}
              >
                {t.hospital.estimates.attention.sort}
              </button>
            ) : null}
          </div>
        </div>
      </div>
      <p className="hos-note">
        {joined
          ? t.hospital.waiting.table.withEstimates(
              modelName,
              fmtDate(detail.origin),
            )
          : t.hospital.waiting.table.noPredictions}
      </p>
      {joined && (attention || order === "highest_refusal_risk") ? (
        <div className="hos-attention-note" role="note">
          <strong>{t.hospital.estimates.attention.title}</strong>
          <p>
            {t.hospital.estimates.attention.rule(
              fmtPercent(joined.attention.threshold, 0),
            )}
          </p>
          <p>{t.hospital.estimates.attention.use}</p>
        </div>
      ) : null}
      <div className="hos-table-scroll">
        <table
          className="hos-table"
          aria-label={t.hospital.waiting.table.title}
        >
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
                  ) : c.key === "refused" ? (
                    <>
                      {c.label}{" "}
                      <em className="hos-col-note">
                        {t.hospital.estimates.byDay(30)}
                      </em>
                    </>
                  ) : c.key === "admitted" ? (
                    <>
                      {c.label}{" "}
                      <em className="hos-col-note">
                        {t.hospital.estimates.byDay(14)}
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
      {joined ? (
        <p className="hos-sub-hint">{t.hospital.estimates.tierHint}</p>
      ) : null}
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
    </div>
  );
}
