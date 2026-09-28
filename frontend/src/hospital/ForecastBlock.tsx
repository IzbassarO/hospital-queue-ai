/**
 * "Что будет" — the 14-day flow published at the origin for one hospital × profile.
 *
 * Every value is read from the publication: the p50 line, the calibrated 80 % band, the historical threshold and
 * the first crossing date. Nothing is recomputed here, and nothing measured after the origin appears in this block.
 */
import { t } from "../i18n";
import { fmtDate, fmtNumber } from "../lib/format";
import { Sparkline } from "../tower/components/Sparkline";
import type { ForecastSeries, SignalView } from "../api/operational-adapters";

const SEVERITY_CLASS: Record<string, string> = {
  HIGH: "is-high",
  ELEVATED: "is-elevated",
  WATCH: "is-watch",
};

export function ForecastBlock({
  series,
  signal,
  origin,
}: {
  series: ForecastSeries | null;
  signal: SignalView | null;
  origin: string;
}) {
  const points = (series?.points ?? []).filter((p) => p.central !== null);
  const threshold = signal?.rawThreshold ?? null;
  const crossing = signal?.rawCrossing ?? null;
  const peak = points.length
    ? Math.max(...points.map((p) => p.central as number))
    : null;
  return (
    <section className="hos-block" aria-label={t.hospital.forecast.title}>
      <div className="block-head">
        <h2>{t.hospital.forecast.title}</h2>
        <p>{t.hospital.forecast.subtitle(fmtDate(origin))}</p>
      </div>
      {points.length === 0 ? (
        <div className="hos-empty" role="status">
          <h3>{t.hospital.forecast.empty}</h3>
          <p>{t.hospital.forecast.emptyHint}</p>
        </div>
      ) : (
        <>
          <Sparkline
            points={points.map((p) => ({
              date: p.date,
              central: p.central as number,
              interval: p.interval,
            }))}
            threshold={threshold}
            crossing={crossing}
          />
          <dl className="hos-facts">
            <div>
              <dt>{t.hospital.forecast.facts.threshold}</dt>
              <dd>
                {threshold === null
                  ? t.hospital.forecast.noThreshold
                  : fmtNumber(threshold, 1)}
              </dd>
            </div>
            <div className={crossing ? "is-crossing" : ""}>
              <dt>{t.hospital.forecast.facts.crossing}</dt>
              <dd>
                {crossing
                  ? t.hospital.forecast.crossingOn(
                      fmtDate(crossing),
                      signal?.rawLeadDays ?? 0,
                    )
                  : t.hospital.forecast.noCrossing}
              </dd>
            </div>
            <div className={signal ? SEVERITY_CLASS[signal.severity] : ""}>
              <dt>{t.hospital.forecast.facts.severity}</dt>
              <dd>
                {signal ? signal.severity : t.hospital.forecast.severityNone}
              </dd>
            </div>
            <div>
              <dt>{t.hospital.forecast.facts.peak}</dt>
              <dd>{peak === null ? "—" : fmtNumber(peak, 1)}</dd>
            </div>
          </dl>
        </>
      )}
    </section>
  );
}
