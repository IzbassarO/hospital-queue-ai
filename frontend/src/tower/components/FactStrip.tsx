/**
 * The real counters of the data mart, shown next to the synthetic waiting strip so the two are never confused: how
 * many referrals were waiting at the mart as-of date, the median wait and the refusal share. Everything here is a
 * description of what already happened (28 days before the as-of date), not a forecast and not a model signal.
 * The region selector narrows it to one oblast; with no selection it is the whole country.
 */
import { t } from "../../i18n";
import { useOverview } from "../../api/queries";
import { fmtDate, fmtNumber } from "../../lib/format";
import { useRegionFilter } from "../region";
import { PublishedTag } from "./SyntheticState";

export function FactStrip({
  regionName,
}: {
  regionName?: (code: string) => string;
}) {
  const overview = useOverview();
  const [region] = useRegionFilter();
  const data = overview.data;
  const row =
    (region ? data?.regions.find((r) => r.code === region) : data?.national) ??
    null;
  const asOf = data?.as_of_date ?? null;
  const percent = (share: number | null) =>
    share === null ? "—" : `${fmtNumber(share * 100, 1)} %`;
  return (
    <section className="fact-strip" aria-label={t.control.facts.title}>
      <header className="fact-strip-head">
        <strong>{t.control.facts.title}</strong> <PublishedTag />
        <span className="fact-strip-scope">
          {asOf ? t.control.facts.asOf(fmtDate(asOf)) : ""}
          {" · "}
          {region && regionName
            ? t.control.facts.scopeRegion(regionName(region))
            : t.control.facts.scope}
        </span>
      </header>
      {row ? (
        <dl className="fact-cells">
          <div>
            <dd>{fmtNumber(row.queue_now, 0)}</dd>
            <dt>{t.control.facts.queue}</dt>
          </div>
          <div>
            <dd>
              {row.median_wait_28d === null
                ? "—"
                : t.control.queue.days(Math.round(row.median_wait_28d))}
            </dd>
            <dt>{t.control.facts.medianWait}</dt>
          </div>
          <div>
            <dd>{percent(row.refusal_rate_28d)}</dd>
            <dt>{t.control.facts.refusalRate}</dt>
          </div>
        </dl>
      ) : (
        <p className="empty">{t.control.facts.unavailable}</p>
      )}
      <p className="fact-strip-note">{t.control.facts.note}</p>
    </section>
  );
}
