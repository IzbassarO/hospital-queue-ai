/**
 * "Насколько сбылись оценки" — the reliability of the served model's day-14 admission probability.
 *
 * Hindsight, and it lives inside the hindsight block for that reason. The bins come from the publication, which
 * computed them over the whole cohort; this file only draws them. It is deliberately not per hospital: a hundred
 * referrals cannot carry a reliability curve, and a curve drawn on one would invite the reading it cannot bear.
 */
import { t } from "../i18n";
import { fmtNumber, fmtPercent } from "../lib/format";
import type { ReferralEstimatesPublication } from "../api/referral-estimates";

const HORIZON = 14;
/** below this gap between promised and observed there is no systematic bias worth naming */
const BIAS = 0.02;

export function CalibrationPanel({
  publication,
}: {
  publication: ReferralEstimatesPublication;
}) {
  const bins = publication.calibration.bins
    .filter((b) => b.horizon_days === HORIZON && b.outcome === "hospitalized")
    .sort((a, b) => a.bin_index - b.bin_index);
  if (bins.length === 0)
    return (
      <div className="hos-sub">
        <h3>{t.hospital.calibration.title}</h3>
        <p className="hos-sub-hint">{t.hospital.calibration.empty}</p>
      </div>
    );

  const rows = bins.reduce((sum, b) => sum + b.n, 0);
  const predicted =
    bins.reduce((sum, b) => sum + b.mean_predicted * b.n, 0) / rows;
  const observed =
    bins.reduce((sum, b) => sum + b.observed_rate * b.n, 0) / rows;
  const gap = predicted - observed;
  const verdict =
    gap > BIAS
      ? t.hospital.calibration.verdict.over
      : gap < -BIAS
        ? t.hospital.calibration.verdict.under
        : t.hospital.calibration.verdict.close;

  const W = 260;
  const H = 260;
  const pad = { l: 40, r: 12, t: 12, b: 34 };
  const x = (v: number) => pad.l + v * (W - pad.l - pad.r);
  const y = (v: number) => H - pad.b - v * (H - pad.t - pad.b);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const largest = Math.max(...bins.map((b) => b.n));

  return (
    <div className="hos-sub hos-calibration">
      <h3>
        {t.hospital.calibration.title}{" "}
        <em className="hos-hindsight-tag">{t.hospital.hindsight.tag}</em>
      </h3>
      <p className="hos-sub-hint">
        {t.hospital.calibration.lead(
          fmtNumber(publication.calibration.rows, 0),
        )}
      </p>
      <div className="hos-calib-split">
        <figure className="spark hos-calib-chart">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label={`${t.hospital.calibration.title} — ${t.hospital.calibration.horizon}`}
          >
            <title>{t.hospital.calibration.horizon}</title>
            {ticks.map((tick) => (
              <g key={tick} className="spark-grid">
                <line x1={pad.l} x2={W - pad.r} y1={y(tick)} y2={y(tick)} />
                <text x={pad.l - 6} y={y(tick) + 4}>
                  {fmtPercent(tick, 0)}
                </text>
                <text x={x(tick)} y={H - 14} className="spark-x">
                  {fmtPercent(tick, 0)}
                </text>
              </g>
            ))}
            <line
              x1={x(0)}
              y1={y(0)}
              x2={x(1)}
              y2={y(1)}
              className="hos-calib-diagonal"
            />
            <path
              d={bins
                .map(
                  (b, i) =>
                    `${i === 0 ? "M" : "L"}${x(b.mean_predicted)} ${y(b.observed_rate)}`,
                )
                .join("")}
              className="hos-calib-line"
            />
            {bins.map((b) => (
              <circle
                key={b.bin_index}
                cx={x(b.mean_predicted)}
                cy={y(b.observed_rate)}
                r={3 + (b.n / largest) * 2.5}
                className="hos-calib-dot"
              >
                <title>
                  {t.hospital.calibration.point(
                    fmtPercent(b.mean_predicted, 0),
                    fmtPercent(b.observed_rate, 0),
                    b.n,
                  )}
                </title>
              </circle>
            ))}
            <text x={W / 2} y={H - 2} className="spark-x hos-calib-axis">
              {t.hospital.calibration.axisPredicted}
            </text>
          </svg>
          <figcaption className="spark-legend">
            <span>
              <i className="sw sw-calib-dot" />{" "}
              {t.hospital.calibration.axisObserved}
            </span>
            <span>
              <i className="sw sw-calib-diag" />{" "}
              {t.hospital.calibration.diagonal}
            </span>
          </figcaption>
        </figure>
        <div className="hos-calib-table">
          <table
            className="hos-table"
            aria-label={t.hospital.calibration.title}
          >
            <thead>
              <tr>
                <th scope="col" className="is-num">
                  {t.hospital.calibration.columns.band}
                </th>
                <th scope="col" className="is-num is-secondary">
                  {t.hospital.calibration.columns.n}
                </th>
                <th scope="col" className="is-num">
                  {t.hospital.calibration.columns.observed}
                </th>
              </tr>
            </thead>
            <tbody>
              {bins.map((b) => (
                <tr key={b.bin_index}>
                  <td className="is-num">{fmtPercent(b.mean_predicted, 0)}</td>
                  <td className="is-num is-secondary">{fmtNumber(b.n, 0)}</td>
                  <td className="is-num">
                    <b>{fmtPercent(b.observed_rate, 0)}</b>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="hos-note is-hindsight-note">
        {t.hospital.calibration.summary(
          fmtPercent(predicted, 1),
          fmtPercent(observed, 1),
        )}{" "}
        {verdict}
      </p>
    </div>
  );
}
