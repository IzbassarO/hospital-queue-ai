/**
 * "Список на сверку" — the administrative verification order for the hospitalisation bureau.
 *
 * The whole design problem here is framing. A ranked list of referrals is one careless heading away from reading
 * as a list of people to strike off, so three things are structural rather than decorative:
 *
 *  - the list ranks the hospital's whole formal queue and says so beside the count: there is no subset whose
 *    difference could be presented as "the real queue";
 *  - the sentence that the specialist decides comes from the publication and sits above the table, not in a
 *    footnote;
 *  - a row whose estimate rests on thin comparable history says so next to the number, because a low
 *    probability there means missing observations rather than a confident model.
 *
 * Every number is read from the publication. The yield curve is hindsight, is shown against the whole queue's
 * base rate, and is labelled as such.
 */
import { useState } from "react";
import { t, useLang } from "../i18n";
import { fmtDate, fmtNumber, fmtPercent } from "../lib/format";
import {
  useWorklistHospital,
  useWorklistRegions,
  type WorklistArea,
  type WorklistItem,
  type WorklistPublication,
} from "../api/verification-worklist";

const PAGE = 25;
/** The publication carries its sentences in both languages; the screen shows the one the reader is reading in. */
type Localised = { ru: string; kk: string };

/** below this best lift, or with any point under the base, the panel says the order helps only modestly */
const WEAK_LIFT = 1.5;

function RuleBox({
  publication,
  lang,
}: {
  publication: WorklistPublication;
  lang: "ru" | "kk";
}) {
  return (
    <div className="hos-rule">
      <h3>{t.hospital.worklist.rule}</h3>
      <p>{(publication.ranking.definition as Localised)[lang]}</p>
      <p className="hos-sub-hint">{t.hospital.worklist.ruleHint}</p>
      <p className="hos-sub-hint">
        {(publication.legacy_rule.statement as Localised)[lang]}
      </p>
    </div>
  );
}

function YieldPanel({
  publication,
  lang,
}: {
  publication: WorklistPublication;
  lang: "ru" | "kk";
}) {
  const { base, points } = publication.yield_curve;
  if (points.length === 0) return null;
  const best = points.reduce((top, point) =>
    point.lift > top.lift ? point : top,
  );
  const weak = best.lift < WEAK_LIFT || points.some((point) => point.lift < 1);
  return (
    <div className="hos-sub hos-yield">
      <h3>
        {t.hospital.worklist.yieldTitle}{" "}
        <em className="hos-hindsight-tag">{t.hospital.hindsight.tag}</em>
      </h3>
      <p className="hos-yield-lead">
        {t.hospital.worklist.yieldLead(
          fmtPercent(base.share, 1),
          fmtNumber(best.checked, 0),
          fmtPercent(best.share, 1),
          fmtNumber(best.lift, 2),
        )}
      </p>
      <p className="hos-sub-hint">
        {(publication.yield_curve.definition as Localised)[lang]}
      </p>
      <div className="hos-table-scroll">
        <table
          className="hos-table"
          aria-label={t.hospital.worklist.yieldTitle}
        >
          <thead>
            <tr>
              <th scope="col" className="is-num">
                {t.hospital.worklist.yieldColumns.checked}
              </th>
              <th scope="col" className="is-num is-secondary">
                {t.hospital.worklist.yieldColumns.found}
              </th>
              <th scope="col" className="is-num">
                {t.hospital.worklist.yieldColumns.share}
              </th>
              <th scope="col" className="is-num">
                {t.hospital.worklist.yieldColumns.lift}
              </th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.checked}>
                <td className="is-num">{fmtNumber(point.checked, 0)}</td>
                <td className="is-num is-secondary">
                  {fmtNumber(point.no_longer_current, 0)}
                </td>
                <td className="is-num">
                  <b>{fmtPercent(point.share, 1)}</b>
                </td>
                <td className="is-num">{fmtNumber(point.lift, 2)}×</td>
              </tr>
            ))}
            <tr className="is-own">
              <th scope="row">{t.hospital.worklist.yieldBase}</th>
              <td className="is-num is-secondary">
                {fmtNumber(base.no_longer_current, 0)}
              </td>
              <td className="is-num">
                <b>{fmtPercent(base.share, 1)}</b>
              </td>
              <td className="is-num">1×</td>
            </tr>
          </tbody>
        </table>
      </div>
      {weak ? (
        <p className="hos-sub-hint">{t.hospital.worklist.yieldWeak}</p>
      ) : null}
    </div>
  );
}

function RegionView({
  own,
  regions,
}: {
  own: WorklistArea;
  regions: WorklistArea[];
}) {
  const [open, setOpen] = useState(false);
  const shown = open ? regions : regions.filter((r) => r.code === own.code);
  return (
    <div className="hos-sub">
      <h3>{t.hospital.worklist.regionTitle}</h3>
      <p className="hos-sub-hint">{t.hospital.worklist.regionLead}</p>
      <div className="hos-table-scroll">
        <table
          className="hos-table"
          aria-label={t.hospital.worklist.regionTitle}
        >
          <thead>
            <tr>
              <th scope="col">{t.hospital.worklist.regionColumns.region}</th>
              <th scope="col" className="is-num">
                {t.hospital.worklist.regionColumns.warning}
              </th>
              <th scope="col" className="is-num">
                {t.hospital.worklist.regionColumns.formal}
              </th>
              <th scope="col" className="is-num">
                {t.hospital.worklist.regionColumns.share}
              </th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr
                key={row.code}
                className={row.code === own.code ? "is-own" : ""}
              >
                <th scope="row">
                  {row.name}
                  {row.code === own.code ? (
                    <small>{t.hospital.worklist.thisRegion}</small>
                  ) : null}
                </th>
                <td className="is-num">
                  <b>{fmtNumber(row.history_quality_warning_count, 0)}</b>
                </td>
                <td className="is-num">
                  {fmtNumber(row.formal_queue_count, 0)}
                </td>
                <td className="is-num">
                  {fmtPercent(row.history_quality_warning_share, 1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {regions.length > 1 ? (
        <button
          type="button"
          className="btn-sm"
          onClick={() => setOpen((value) => !value)}
        >
          {open
            ? t.hospital.worklist.hideRegions
            : t.hospital.worklist.showAllRegions}
        </button>
      ) : null}
    </div>
  );
}

function ItemRows({
  items,
  publication,
  lang,
}: {
  items: WorklistItem[];
  publication: WorklistPublication;
  lang: "ru" | "kk";
}) {
  const definition = (publication.history_quality.definition as Localised)[
    lang
  ];
  return (
    <tbody>
      {items.map((row) => (
        <tr key={row.referral_id}>
          <td className="is-num is-rank">{fmtNumber(row.rank, 0)}</td>
          <td className="is-code">
            {row.hospitalization_code ?? row.referral_id}
          </td>
          <td className="is-secondary">{row.profile_name}</td>
          <td className="is-num">{fmtNumber(row.days_waited_at_origin, 0)}</td>
          <td className="is-num">
            <b className="hos-est-head">
              {fmtPercent(row.probability_admitted_horizon, 0)}
            </b>
            <small>{t.hospital.estimates.byDay(row.horizon_days)}</small>
          </td>
          {/* The history-quality mark sits with the priority rather than in the secondary support column,
              because a phone drops that column and this is exactly the qualifier a reader must not lose. */}
          <td>
            <span
              className="hos-worklist-reason"
              title={t.hospital.worklist.table.priorityHint}
            >
              {fmtNumber(row.verification_priority_score, 2)}
            </span>
            {row.history_quality_reason_code ? (
              <small
                className="hos-degenerate"
                title={`${t.hospital.worklist.history.reasons[row.history_quality_reason_code]}. ${definition}`}
              >
                {t.hospital.worklist.history.tag}
              </small>
            ) : null}
          </td>
          <td className="is-secondary">
            <span className={`hos-tier is-${row.estimate_tier}`}>
              {
                t.hospital.estimates.tier[
                  row.estimate_tier === "global"
                    ? "national"
                    : row.estimate_tier
                ]
              }
            </span>
          </td>
        </tr>
      ))}
    </tbody>
  );
}

export function VerificationBlock({
  org,
  publication,
}: {
  org: string;
  publication: WorklistPublication;
}) {
  const lang = useLang();
  const [order, setOrder] = useState<"rank" | "longest_wait">("rank");
  const [warningOnly, setWarningOnly] = useState(false);
  const [page, setPage] = useState(0);
  const query = {
    order,
    historyWarning: warningOnly ? true : null,
    limit: PAGE,
    offset: page * PAGE,
  };
  const worklist = useWorklistHospital(org, query);
  const regions = useWorklistRegions();
  const data = worklist.data;
  const reset = () => setPage(0);

  if (!data) return null;
  const items = data.items;

  return (
    <div className="hos-worklist">
      <div className="block-head">
        <h3>{t.hospital.worklist.title}</h3>
        <p>{t.hospital.worklist.subtitle(fmtDate(data.origin))}</p>
      </div>
      {/* the publication's own sentence, above the list rather than under it */}
      <p className="hos-decision" role="note">
        {(data.not_a_decision as Localised)[lang]}
      </p>
      <p className="hos-note">
        {t.hospital.worklist.notAQueue(fmtNumber(data.formal_queue_count, 0))}
      </p>

      {/* every tile in this row is this hospital's own number; the publication-wide total lives in the panel */}
      <dl className="hos-totals">
        <div>
          <dd>{fmtNumber(data.formal_queue_count, 0)}</dd>
          <dt>{t.hospital.worklist.totals.formal}</dt>
        </div>
        <div>
          <dd>{fmtNumber(data.history_quality_warning_count, 0)}</dd>
          <dt>{t.hospital.worklist.totals.warning}</dt>
        </div>
        <div>
          <dd>{fmtPercent(data.history_quality_warning_share, 1)}</dd>
          <dt>{t.hospital.worklist.totals.warningShare}</dt>
        </div>
      </dl>

      <RuleBox publication={publication} lang={lang} />

      <div className="hos-table-head">
        <h3>{t.hospital.worklist.table.title}</h3>
        <div className="hos-table-controls">
          <label className="hos-check">
            <input
              type="checkbox"
              checked={warningOnly}
              onChange={(e) => {
                setWarningOnly(e.target.checked);
                reset();
              }}
            />
            <span>
              {warningOnly
                ? t.hospital.worklist.history.filter
                : t.hospital.worklist.history.all}
            </span>
          </label>
          <div className="hos-segment" role="group">
            <button
              type="button"
              className={order === "rank" ? "is-on" : ""}
              aria-pressed={order === "rank"}
              onClick={() => {
                setOrder("rank");
                reset();
              }}
            >
              {t.hospital.worklist.order.rank}
            </button>
            <button
              type="button"
              className={order === "longest_wait" ? "is-on" : ""}
              aria-pressed={order === "longest_wait"}
              onClick={() => {
                setOrder("longest_wait");
                reset();
              }}
            >
              {t.hospital.worklist.order.longest}
            </button>
          </div>
        </div>
      </div>
      <div className="hos-table-scroll">
        <table
          className="hos-table hos-worklist-table"
          aria-label={t.hospital.worklist.table.title}
        >
          <thead>
            <tr>
              <th
                scope="col"
                className="is-num is-rank"
                title={t.hospital.worklist.table.rankHint}
              >
                {t.hospital.worklist.table.rank}
              </th>
              <th scope="col" className="is-code">
                {t.hospital.worklist.table.code}
              </th>
              <th scope="col" className="is-secondary">
                {t.hospital.worklist.table.profile}
              </th>
              <th scope="col" className="is-num">
                {t.hospital.worklist.table.waited}
              </th>
              <th scope="col" className="is-num">
                {t.hospital.worklist.table.chance}
              </th>
              <th scope="col" title={t.hospital.worklist.table.priorityHint}>
                {t.hospital.worklist.table.priority}
              </th>
              <th scope="col" className="is-secondary">
                {t.hospital.worklist.table.support}
              </th>
            </tr>
          </thead>
          <ItemRows items={items} publication={publication} lang={lang} />
        </table>
      </div>
      <p className="hos-sub-hint">{t.hospital.worklist.history.hint}</p>
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
            data.total === 0 ? 0 : page * PAGE + 1,
            Math.min(data.total, (page + 1) * PAGE),
            data.total,
          )}
        </span>
        <button
          type="button"
          className="btn-sm"
          disabled={(page + 1) * PAGE >= data.total}
          onClick={() => setPage((p) => p + 1)}
        >
          {t.hospital.waiting.table.next}
        </button>
      </div>

      <div className="hos-split">
        <YieldPanel publication={publication} lang={lang} />
        <RegionView own={data.region} regions={regions.data ?? [data.region]} />
      </div>
      <p className="hos-decision is-repeat" role="note">
        {(data.not_a_decision as Localised)[lang]}
      </p>
      <p className="hos-sub-hint">
        {t.hospital.worklist.source(
          publication.publication_id,
          publication.source_publication.publication_id,
        )}
      </p>
    </div>
  );
}
