/**
 * Forecast story chart (SVG): observed registrations up to the origin, then the published central forecast with
 * its calibrated interval, the historical-flow reference and the first crossing. Values are drawn as published.
 */
import { useId } from "react";
import { t } from "../../i18n";
import { fmtDayMonth, fmtNumber } from "../../lib/format";
import { Legend } from "../primitives";
import { niceTicks } from "./scale";

export interface ForecastPoint {
  date: string;
  central: number | null;
  interval: [number, number] | null;
}
export interface ObservedPoint {
  date: string;
  registrations: number;
}

const W = 960;
const H = 380;
const PAD = { top: 28, right: 24, bottom: 40, left: 52 };

export function ForecastStory({
  observed,
  forecast,
  threshold,
  crossing,
  coverage,
  observedDays = 28,
}: {
  observed: ObservedPoint[];
  forecast: ForecastPoint[];
  threshold: number | null;
  crossing: string | null;
  coverage: string | null;
  observedDays?: number;
}) {
  const id = useId();
  const history = observed.slice(-observedDays);
  const dates = [...history.map((p) => p.date), ...forecast.map((p) => p.date)];
  const n = Math.max(dates.length, 1);
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const step = innerW / n;
  const x = (i: number) => PAD.left + step * (i + 0.5);
  // The axis is anchored to the forecast evidence; an observed bar above it is clipped and labelled with its value.
  const forecastValues = [
    ...forecast.flatMap((p) => [p.central ?? 0, p.interval?.[1] ?? 0]),
    threshold ?? 0,
  ];
  const observedMax = Math.max(0, ...history.map((p) => p.registrations));
  const forecastMax = Math.max(1, ...forecastValues);
  const yMax =
    (observedMax <= forecastMax * 1.6
      ? Math.max(forecastMax, observedMax)
      : forecastMax) * 1.12;
  const y = (v: number) => PAD.top + innerH - (v / yMax) * innerH;
  const ticks = niceTicks(yMax, 4);
  const forecastOffset = history.length;
  const band = forecast
    .map((p, i) => ({ i: i + forecastOffset, band: p.interval }))
    .filter((p): p is { i: number; band: [number, number] } => p.band !== null);
  const bandPath = band.length
    ? `M ${band.map((p) => `${x(p.i)},${y(p.band[1])}`).join(" L ")} L ${[
        ...band,
      ]
        .reverse()
        .map((p) => `${x(p.i)},${y(p.band[0])}`)
        .join(" L ")} Z`
    : "";
  const linePoints = forecast
    .map((p, i) =>
      p.central === null ? null : `${x(i + forecastOffset)},${y(p.central)}`,
    )
    .filter((p): p is string => p !== null);
  const linePath = linePoints.length ? `M ${linePoints.join(" L ")}` : "";
  const originIndex = forecastOffset - 0.5;
  const crossingIndex = crossing ? dates.indexOf(crossing) : -1;
  const labelEvery = Math.max(1, Math.ceil(n / 12));
  return (
    <figure className="story-chart" aria-label={t.demo.understand.chartTitle}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby={`${id}-title`}
        className="story-svg"
      >
        <title id={`${id}-title`}>{t.demo.understand.chartTitle}</title>
        <defs>
          <linearGradient id={`${id}-band`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" className="band-stop-top" />
            <stop offset="1" className="band-stop-bottom" />
          </linearGradient>
          <clipPath id={`${id}-clip`}>
            <rect
              className="reveal-clip"
              x={PAD.left}
              y={0}
              width={innerW}
              height={H}
            />
          </clipPath>
        </defs>
        {ticks.map((tick) => (
          <g key={tick} className="grid-line">
            <line x1={PAD.left} x2={W - PAD.right} y1={y(tick)} y2={y(tick)} />
            <text x={PAD.left - 10} y={y(tick) + 4} textAnchor="end">
              {fmtNumber(tick, tick < 10 && !Number.isInteger(tick) ? 1 : 0)}
            </text>
          </g>
        ))}
        {history.map((p, i) => {
          const clipped = p.registrations > yMax;
          const top = y(Math.min(p.registrations, yMax));
          return (
            <g key={p.date}>
              <rect
                className={`observed-bar ${clipped ? "is-clipped" : ""}`}
                x={x(i) - step * 0.32}
                y={top}
                width={step * 0.64}
                height={Math.max(0, y(0) - top)}
              >
                <title>{`${fmtDayMonth(p.date)}: ${fmtNumber(p.registrations, 0)}`}</title>
              </rect>
              {clipped ? (
                <text
                  className="observed-label"
                  x={x(i)}
                  y={top + 14}
                  textAnchor="middle"
                >
                  {fmtNumber(p.registrations, 0)}
                </text>
              ) : null}
            </g>
          );
        })}
        {forecastOffset > 0 ? (
          <g className="origin-mark">
            <line
              x1={x(originIndex)}
              x2={x(originIndex)}
              y1={PAD.top - 8}
              y2={y(0)}
            />
            <text x={x(originIndex) - 8} y={PAD.top + 2} textAnchor="end">
              {t.demo.understand.originMark}
            </text>
          </g>
        ) : null}
        {threshold !== null ? (
          <g className="threshold-mark">
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(threshold)}
              y2={y(threshold)}
            />
            <text x={PAD.left + 6} y={y(threshold) - 7} textAnchor="start">
              {t.demo.understand.threshold} · {fmtNumber(threshold, 1)}
            </text>
          </g>
        ) : null}
        <g clipPath={`url(#${id}-clip)`}>
          {bandPath ? (
            <path
              className="band-area"
              d={bandPath}
              fill={`url(#${id}-band)`}
            />
          ) : null}
          {linePath ? (
            <path className="central-line reveal-line" d={linePath} />
          ) : null}
          {forecast.map((p, i) =>
            p.central === null ? null : (
              <circle
                key={p.date}
                className="central-dot"
                cx={x(i + forecastOffset)}
                cy={y(p.central)}
                r={4}
              >
                <title>{`${fmtDayMonth(p.date)}: ${fmtNumber(p.central, 1)}${
                  p.interval
                    ? ` (${fmtNumber(p.interval[0], 1)} – ${fmtNumber(p.interval[1], 1)})`
                    : ""
                }`}</title>
              </circle>
            ),
          )}
        </g>
        {crossingIndex >= 0 ? (
          <g className="crossing-mark">
            <line
              x1={x(crossingIndex)}
              x2={x(crossingIndex)}
              y1={PAD.top + 8}
              y2={y(0)}
            />
            <text x={x(crossingIndex) + 8} y={PAD.top + 2} textAnchor="start">
              {t.demo.understand.crossing} · {fmtDayMonth(crossing!)}
            </text>
          </g>
        ) : null}
        {dates.map((d, i) =>
          i % labelEvery === 0 || i === n - 1 ? (
            <text
              key={d}
              className="axis-label"
              x={x(i)}
              y={H - 14}
              textAnchor="middle"
            >
              {fmtDayMonth(d)}
            </text>
          ) : null,
        )}
      </svg>
      <figcaption>
        <Legend
          items={[
            ...(history.length
              ? [
                  {
                    swatch: "swatch-observed",
                    label: t.demo.understand.observed,
                  },
                ]
              : []),
            { swatch: "swatch-central", label: t.demo.understand.forecast },
            {
              swatch: "swatch-band",
              label: coverage
                ? `${t.demo.understand.band} · ${coverage}`
                : t.demo.understand.band,
            },
            { swatch: "swatch-threshold", label: t.demo.understand.threshold },
          ]}
        />
      </figcaption>
    </figure>
  );
}
