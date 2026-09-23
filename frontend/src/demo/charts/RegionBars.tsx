/** Compact network context: published HIGH-signal counts per region, the subject region highlighted. */
import { fmtNumber } from "../../lib/format";
import { t } from "../../i18n";

export function RegionBars({
  regions,
  highlight,
  names,
  limit = 8,
}: {
  regions: { code: string; high: number; total: number }[];
  highlight: string | null;
  names: (code: string) => string;
  limit?: number;
}) {
  const sorted = [...regions].sort(
    (a, b) => b.high - a.high || a.code.localeCompare(b.code),
  );
  const shown = sorted.slice(0, limit);
  if (highlight && !shown.some((r) => r.code === highlight)) {
    const own = sorted.find((r) => r.code === highlight);
    if (own) shown.push(own);
  }
  const max = Math.max(1, ...shown.map((r) => r.high));
  return (
    <ol className="region-bars" aria-label={t.demo.detect.nationalTitle}>
      {shown.map((r) => (
        <li key={r.code} className={r.code === highlight ? "is-highlight" : ""}>
          <span className="region-name">{names(r.code)}</span>
          <span className="region-track" aria-hidden="true">
            <span
              className="region-fill reveal-bar"
              style={{ width: `${(r.high / max) * 100}%` }}
            />
          </span>
          <span className="region-count">{fmtNumber(r.high, 0)}</span>
        </li>
      ))}
    </ol>
  );
}
