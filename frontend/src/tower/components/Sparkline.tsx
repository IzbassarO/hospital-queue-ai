/** Fourteen-day forecast of one series: central line, calibrated band, threshold. Compact, single axis. */
import { t } from "../../i18n";
import { fmtDayMonth, fmtNumber } from "../../lib/format";
import { niceTicks } from "../../demo/charts/scale";

export interface SparkPoint {
  date: string;
  central: number;
  interval: [number, number] | null;
}

export function Sparkline({
  points,
  threshold,
  crossing,
}: {
  points: SparkPoint[];
  threshold: number | null;
  crossing: string | null;
}) {
  const W = 520;
  const H = 180;
  const pad = { l: 34, r: 12, t: 12, b: 24 };
  const values = points.flatMap((p) => [p.central, ...(p.interval ?? [])]);
  if (threshold !== null) values.push(threshold);
  const max = Math.max(1, ...values);
  const ticks = niceTicks(max, 3);
  const top = ticks.at(-1) ?? max;
  const tickDecimals = (ticks[1] ?? 1) < 1 ? 1 : 0;
  const x = (i: number) =>
    pad.l + (i / Math.max(1, points.length - 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - v / top) * (H - pad.t - pad.b);
  const line = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i)} ${y(p.central)}`)
    .join("");
  const band = points.every((p) => p.interval)
    ? [
        ...points.map(
          (p, i) => `${i === 0 ? "M" : "L"}${x(i)} ${y(p.interval![1])}`,
        ),
        ...[...points]
          .reverse()
          .map((p, j) => `L${x(points.length - 1 - j)} ${y(p.interval![0])}`),
        "Z",
      ].join("")
    : null;
  const crossIndex = crossing
    ? points.findIndex((p) => p.date === crossing)
    : -1;
  return (
    <figure className="spark">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={t.control.focus.forecastTitle}
      >
        <title>{t.control.focus.forecastTitle}</title>
        {ticks.map((tick) => (
          <g key={tick} className="spark-grid">
            <line x1={pad.l} x2={W - pad.r} y1={y(tick)} y2={y(tick)} />
            <text x={pad.l - 6} y={y(tick) + 4}>
              {fmtNumber(tick, tickDecimals)}
            </text>
          </g>
        ))}
        {band ? <path d={band} className="spark-band" /> : null}
        {threshold !== null ? (
          <line
            x1={pad.l}
            x2={W - pad.r}
            y1={y(threshold)}
            y2={y(threshold)}
            className="spark-threshold"
          />
        ) : null}
        {crossIndex >= 0 ? (
          <line
            x1={x(crossIndex)}
            x2={x(crossIndex)}
            y1={pad.t}
            y2={H - pad.b}
            className="spark-crossing"
          />
        ) : null}
        <path d={line} className="spark-line" />
        {points.map((p, i) =>
          i === 0 || i === points.length - 1 || i % 4 === 0 ? (
            <text key={p.date} x={x(i)} y={H - 6} className="spark-x">
              {fmtDayMonth(p.date)}
            </text>
          ) : null,
        )}
      </svg>
      <figcaption className="spark-legend">
        <span>
          <i className="sw sw-line" /> {t.control.focus.central}
        </span>
        <span>
          <i className="sw sw-band" /> {t.control.focus.band}
        </span>
        <span>
          <i className="sw sw-threshold" /> {t.control.focus.threshold}
        </span>
      </figcaption>
    </figure>
  );
}
