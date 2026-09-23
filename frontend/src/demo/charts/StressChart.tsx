/** Baseline versus stress scenario (SVG): accepted central + calibrated bounds against the scenario central + derived range. */
import { useId } from "react";
import { t } from "../../i18n";
import { fmtDayMonth, fmtNumber } from "../../lib/format";
import { Legend } from "../primitives";
import { niceTicks } from "./scale";

export interface StressCell {
  target_date: string;
  baseline_central: number;
  baseline_lower: number | null;
  baseline_upper: number | null;
  scenario_central: number;
  scenario_lower: number | null;
  scenario_upper: number | null;
  threshold_value: number | null;
  severity_changed: boolean;
}

const W = 960;
const H = 340;
const PAD = { top: 24, right: 24, bottom: 40, left: 52 };

function area(
  cells: StressCell[],
  x: (i: number) => number,
  y: (v: number) => number,
  lower: (c: StressCell) => number | null,
  upper: (c: StressCell) => number | null,
): string {
  const pts = cells
    .map((c, i) => ({ i, lo: lower(c), hi: upper(c) }))
    .filter(
      (p): p is { i: number; lo: number; hi: number } =>
        p.lo !== null && p.hi !== null,
    );
  if (!pts.length) return "";
  return `M ${pts.map((p) => `${x(p.i)},${y(p.hi)}`).join(" L ")} L ${[...pts]
    .reverse()
    .map((p) => `${x(p.i)},${y(p.lo)}`)
    .join(" L ")} Z`;
}

export function StressChart({
  cells,
  scenarioLabel,
  isIdentity,
}: {
  cells: StressCell[];
  scenarioLabel: string;
  isIdentity: boolean;
}) {
  const id = useId();
  const n = Math.max(cells.length, 1);
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (innerW / n) * (i + 0.5);
  const yMax =
    Math.max(
      1,
      ...cells.flatMap((c) => [
        c.baseline_upper ?? c.baseline_central,
        c.scenario_upper ?? c.scenario_central,
        c.threshold_value ?? 0,
      ]),
    ) * 1.08;
  const y = (v: number) => PAD.top + innerH - (v / yMax) * innerH;
  const baselineBand = area(
    cells,
    x,
    y,
    (c) => c.baseline_lower,
    (c) => c.baseline_upper,
  );
  const scenarioBand = area(
    cells,
    x,
    y,
    (c) => c.scenario_lower,
    (c) => c.scenario_upper,
  );
  const line = (pick: (c: StressCell) => number) =>
    cells.length
      ? `M ${cells.map((c, i) => `${x(i)},${y(pick(c))}`).join(" L ")}`
      : "";
  const threshold = cells.length
    ? `M ${cells.map((c, i) => `${x(i) - innerW / n / 2},${y(c.threshold_value ?? 0)} L ${x(i) + innerW / n / 2},${y(c.threshold_value ?? 0)}`).join(" M ")}`
    : "";
  return (
    <figure className="story-chart" aria-label={t.demo.test.chartTitle}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby={`${id}-t`}
        className="story-svg"
      >
        <title
          id={`${id}-t`}
        >{`${t.demo.test.chartTitle}: ${scenarioLabel}`}</title>
        {niceTicks(yMax, 4).map((tick) => (
          <g key={tick} className="grid-line">
            <line x1={PAD.left} x2={W - PAD.right} y1={y(tick)} y2={y(tick)} />
            <text x={PAD.left - 10} y={y(tick) + 4} textAnchor="end">
              {fmtNumber(tick, 0)}
            </text>
          </g>
        ))}
        {baselineBand ? (
          <path className="band-baseline" d={baselineBand} />
        ) : null}
        <path className="line-baseline" d={line((c) => c.baseline_central)} />
        {!isIdentity ? (
          <g className="scenario-layer" key={scenarioLabel}>
            {scenarioBand ? (
              <path className="band-scenario" d={scenarioBand} />
            ) : null}
            <path
              className="line-scenario reveal-line"
              d={line((c) => c.scenario_central)}
            />
            {cells.map((c, i) => (
              <circle
                key={c.target_date}
                className={`scenario-dot ${c.severity_changed ? "is-changed" : ""}`}
                cx={x(i)}
                cy={y(c.scenario_central)}
                r={c.severity_changed ? 5 : 3.5}
              >
                <title>{`${fmtDayMonth(c.target_date)}: ${fmtNumber(c.baseline_central, 1)} → ${fmtNumber(c.scenario_central, 1)}`}</title>
              </circle>
            ))}
          </g>
        ) : (
          cells.map((c, i) => (
            <circle
              key={c.target_date}
              className="central-dot"
              cx={x(i)}
              cy={y(c.baseline_central)}
              r={3.5}
            >
              <title>{`${fmtDayMonth(c.target_date)}: ${fmtNumber(c.baseline_central, 1)}`}</title>
            </circle>
          ))
        )}
        {threshold ? <path className="threshold-steps" d={threshold} /> : null}
        {cells.map((c, i) =>
          i % 2 === 0 || i === n - 1 ? (
            <text
              key={c.target_date}
              className="axis-label"
              x={x(i)}
              y={H - 14}
              textAnchor="middle"
            >
              {fmtDayMonth(c.target_date)}
            </text>
          ) : null,
        )}
      </svg>
      <figcaption>
        <Legend
          items={[
            { swatch: "swatch-baseline", label: t.demo.test.baseline },
            { swatch: "swatch-band-muted", label: t.tower.interval },
            ...(isIdentity
              ? []
              : [
                  {
                    swatch: "swatch-scenario",
                    label: `${t.demo.test.scenario} ${scenarioLabel}`,
                  },
                  { swatch: "swatch-band", label: t.demo.test.sensitivity },
                ]),
            { swatch: "swatch-threshold", label: t.demo.understand.threshold },
          ]}
        />
      </figcaption>
    </figure>
  );
}
