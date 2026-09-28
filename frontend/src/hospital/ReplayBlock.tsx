/**
 * "Что было на самом деле" — 18.03 … 31.03, one day at a time: the interval published at the origin against the
 * flow that actually arrived.
 *
 * The forecast half is read from the publication and never moves. The actual half is hindsight: it did not exist
 * on the origin date, so it is revealed only as the clock walks forward, carries the "ретроспектива" tag in the
 * block header and in the verdict column, and is never fed back into anything.
 *
 * The clock is remount state: the parent keys this block by profile, so switching profile starts a fresh replay
 * rather than leaving a half-played one on screen.
 */
import { useEffect, useRef, useState } from "react";
import { t } from "../i18n";
import { fmtDate, fmtDayMonth, fmtNumber } from "../lib/format";
import { GlyphPause, GlyphPlay, GlyphReplay } from "../demo/glyphs";
import { niceTicks } from "../demo/charts/scale";
import type { ReplayDay } from "./useHospitalProfile";

const STEP_MS = 900;

function ReplayChart({ days, upTo }: { days: ReplayDay[]; upTo: number }) {
  const W = 560;
  const H = 200;
  const pad = { l: 34, r: 12, t: 12, b: 26 };
  const values = days.flatMap((d) => [
    ...(d.interval ?? []),
    ...(d.central === null ? [] : [d.central]),
    ...(d.actual === null ? [] : [d.actual]),
  ]);
  const ticks = niceTicks(Math.max(1, ...values), 3);
  const top = ticks.at(-1) ?? 1;
  const x = (i: number) =>
    pad.l + (i / Math.max(1, days.length - 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - v / top) * (H - pad.t - pad.b);
  const banded = days.filter((d) => d.interval);
  const band = banded.length
    ? [
        ...days.map((d, i) =>
          d.interval ? `${i === 0 ? "M" : "L"}${x(i)} ${y(d.interval[1])}` : "",
        ),
        ...[...days]
          .reverse()
          .map((d, j) =>
            d.interval ? `L${x(days.length - 1 - j)} ${y(d.interval[0])}` : "",
          ),
        "Z",
      ].join("")
    : null;
  const central = days
    .map((d, i) =>
      d.central === null ? "" : `${i === 0 ? "M" : "L"}${x(i)} ${y(d.central)}`,
    )
    .join("");
  const shown = days.slice(0, upTo);
  const actualLine = shown
    .map((d, i) =>
      d.actual === null ? "" : `${i === 0 ? "M" : "L"}${x(i)} ${y(d.actual)}`,
    )
    .join("");
  return (
    <figure className="spark hos-replay-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={t.hospital.replay.title}
      >
        <title>{t.hospital.replay.title}</title>
        {ticks.map((tick) => (
          <g key={tick} className="spark-grid">
            <line x1={pad.l} x2={W - pad.r} y1={y(tick)} y2={y(tick)} />
            <text x={pad.l - 6} y={y(tick) + 4}>
              {fmtNumber(tick, 0)}
            </text>
          </g>
        ))}
        {band ? <path d={band} className="spark-band" /> : null}
        <path d={central} className="spark-line" />
        <path d={actualLine} className="hos-actual-line" />
        {shown.map((d, i) =>
          d.actual === null ? null : (
            <circle
              key={d.date}
              cx={x(i)}
              cy={y(d.actual)}
              r={i === shown.length - 1 ? 5 : 3.5}
              className={`hos-actual-dot is-${d.verdict}`}
            />
          ),
        )}
        {days.map((d, i) =>
          i === 0 || i === days.length - 1 || i % 3 === 0 ? (
            <text key={d.date} x={x(i)} y={H - 6} className="spark-x">
              {fmtDayMonth(d.date)}
            </text>
          ) : null,
        )}
      </svg>
      <figcaption className="spark-legend">
        <span>
          <i className="sw sw-band" /> {t.hospital.replay.expected}
        </span>
        <span>
          <i className="sw sw-actual" /> {t.hospital.replay.actual}
        </span>
      </figcaption>
    </figure>
  );
}

export function ReplayBlock({
  days,
  origin,
}: {
  days: ReplayDay[];
  origin: string;
}) {
  const [upTo, setUpTo] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!playing) return;
    timer.current = window.setInterval(() => {
      setUpTo((current) => {
        if (current >= days.length) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, STEP_MS);
    return () => window.clearInterval(timer.current);
  }, [playing, days.length]);

  if (days.length === 0)
    return (
      <section className="hos-block" aria-label={t.hospital.replay.title}>
        <div className="block-head">
          <h2>{t.hospital.replay.title}</h2>
        </div>
        <div className="hos-empty" role="status">
          <h3>{t.hospital.replay.empty}</h3>
        </div>
      </section>
    );

  const shown = days.slice(0, upTo);
  const scored = shown.filter((d) => d.verdict !== "unknown");
  const inside = scored.filter((d) => d.verdict === "inside").length;
  const finished = upTo >= days.length;

  return (
    <section className="hos-block" aria-label={t.hospital.replay.title}>
      <div className="block-head block-head-row">
        <div>
          <h2>{t.hospital.replay.title}</h2>
          <p>{t.hospital.replay.subtitle}</p>
        </div>
        <em className="hos-hindsight-tag">{t.hospital.hindsight.tag}</em>
      </div>
      <p className="hos-note is-hindsight-note">
        {t.hospital.hindsight.note(fmtDate(origin))} {t.hospital.replay.lead}
      </p>

      <div className="hos-replay-bar">
        <div className="hos-replay-clock">
          <span className="sim-day" role="status" aria-live="polite">
            {upTo === 0
              ? t.hospital.replay.notStarted
              : t.hospital.replay.day(upTo)}
          </span>
          <span className="sim-date">
            {upTo === 0
              ? t.hospital.replay.range(
                  fmtDate(days[0].date),
                  fmtDate(days[days.length - 1].date),
                )
              : `${fmtDate(days[upTo - 1].date)} · ${t.hospital.replay.dayOf(upTo, days.length)}`}
          </span>
          <ol className="sim-track" aria-hidden="true">
            {days.map((d, i) => (
              <li
                key={d.date}
                className={
                  i < upTo - 1 ? "is-past" : i === upTo - 1 ? "is-now" : ""
                }
              />
            ))}
          </ol>
        </div>
        <div className="hos-replay-controls">
          {finished ? (
            <button
              type="button"
              className="btn-lime"
              onClick={() => {
                setUpTo(0);
                setPlaying(false);
              }}
            >
              <GlyphReplay /> {t.hospital.replay.reset}
            </button>
          ) : playing ? (
            <button
              type="button"
              className="btn-lime"
              onClick={() => setPlaying(false)}
            >
              <GlyphPause /> {t.hospital.replay.pause}
            </button>
          ) : (
            <button
              type="button"
              className="btn-lime"
              onClick={() => setPlaying(true)}
            >
              <GlyphPlay /> {t.hospital.replay.start}
            </button>
          )}
          <button
            type="button"
            className="btn-sm"
            disabled={finished}
            onClick={() => {
              setPlaying(false);
              setUpTo((c) => Math.min(days.length, c + 1));
            }}
          >
            {t.hospital.replay.step}
          </button>
          <span className="hos-tally" role="status">
            {scored.length === 0
              ? t.hospital.replay.tallyPending
              : t.hospital.replay.tally(inside, scored.length)}
          </span>
        </div>
      </div>

      <ReplayChart days={days} upTo={upTo} />

      <div className="hos-table-scroll">
        <table className="hos-table hos-replay-table">
          <thead>
            <tr>
              <th scope="col">{t.hospital.replay.columns.date}</th>
              <th scope="col" className="is-num">
                {t.hospital.replay.columns.forecast}
              </th>
              <th scope="col" className="is-num">
                {t.hospital.replay.columns.actual}{" "}
                <em className="hos-hindsight-tag">
                  {t.hospital.hindsight.tag}
                </em>
              </th>
              <th scope="col">{t.hospital.replay.columns.verdict}</th>
            </tr>
          </thead>
          <tbody>
            {days.map((d, i) => {
              const revealed = i < upTo;
              return (
                <tr key={d.date} className={revealed ? "" : "is-future"}>
                  <td>{fmtDate(d.date)}</td>
                  <td className="is-num">
                    {d.interval
                      ? `${fmtNumber(d.interval[0], 1)} – ${fmtNumber(d.interval[1], 1)}`
                      : "—"}
                  </td>
                  <td className="is-num">
                    {revealed && d.actual !== null
                      ? fmtNumber(d.actual, 0)
                      : "—"}
                  </td>
                  <td>
                    {revealed && d.verdict !== "unknown" ? (
                      <span className={`hos-verdict is-${d.verdict}`}>
                        {d.verdict === "inside"
                          ? t.hospital.replay.inBand
                          : d.verdict === "above"
                            ? t.hospital.replay.above
                            : t.hospital.replay.below}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
