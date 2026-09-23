/** Before → alternative comparison for one series (donor or receiver): daily central values against the reference. */
import { useId } from "react";
import { fmtDayMonth, fmtNumber } from "../../lib/format";
import { t } from "../../i18n";
import { niceTicks } from "./scale";

export interface StateCell {
  horizon: number;
  target_date: string;
  central: number;
  threshold_value?: number | null;
  severity: string;
}

const W = 460;
const H = 220;
const PAD = { top: 18, right: 12, bottom: 30, left: 40 };

export function TransferChart({
  title,
  before,
  after,
  tone,
}: {
  title: string;
  before: StateCell[];
  after: StateCell[];
  tone: "donor" | "receiver";
}) {
  const id = useId();
  const n = Math.max(before.length, 1);
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const slot = innerW / n;
  const x = (i: number) => PAD.left + slot * i;
  const yMax =
    Math.max(
      1,
      ...before.map((c) => c.central),
      ...after.map((c) => c.central),
      ...before.map((c) => c.threshold_value ?? 0),
    ) * 1.1;
  const y = (v: number) => PAD.top + innerH - (v / yMax) * innerH;
  return (
    <figure className={`transfer-chart transfer-${tone}`} aria-label={title}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby={`${id}-t`}
        className="story-svg"
      >
        <title id={`${id}-t`}>{title}</title>
        {niceTicks(yMax, 3).map((tick) => (
          <g key={tick} className="grid-line">
            <line x1={PAD.left} x2={W - PAD.right} y1={y(tick)} y2={y(tick)} />
            <text x={PAD.left - 8} y={y(tick) + 4} textAnchor="end">
              {fmtNumber(tick, 0)}
            </text>
          </g>
        ))}
        {before.map((c, i) => {
          const next = after[i];
          const bw = slot * 0.3;
          return (
            <g key={c.target_date}>
              <rect
                className="bar-before"
                x={x(i) + slot * 0.14}
                y={y(c.central)}
                width={bw}
                height={Math.max(0, y(0) - y(c.central))}
              >
                <title>{`${fmtDayMonth(c.target_date)} · ${t.demo.review.before}: ${fmtNumber(c.central, 1)}`}</title>
              </rect>
              {next ? (
                <rect
                  className="bar-after reveal-bar"
                  x={x(i) + slot * 0.14 + bw + slot * 0.06}
                  y={y(next.central)}
                  width={bw}
                  height={Math.max(0, y(0) - y(next.central))}
                >
                  <title>{`${fmtDayMonth(next.target_date)} · ${t.demo.review.after}: ${fmtNumber(next.central, 1)}`}</title>
                </rect>
              ) : null}
              {c.threshold_value != null ? (
                <line
                  className="threshold-tick"
                  x1={x(i) + slot * 0.08}
                  x2={x(i) + slot * 0.92}
                  y1={y(c.threshold_value)}
                  y2={y(c.threshold_value)}
                />
              ) : null}
              {i % 3 === 0 || i === n - 1 ? (
                <text
                  className="axis-label"
                  x={x(i) + slot / 2}
                  y={H - 10}
                  textAnchor="middle"
                >
                  {fmtDayMonth(c.target_date)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
