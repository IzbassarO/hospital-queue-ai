/**
 * The region selector of the shell. State and persistence live in ../region; this file only renders the control.
 */
import { t } from "../../i18n";
import { useRegionFilter } from "../region";
import type { RegionSummary } from "../useTowerData";

export function RegionFilter({ regions }: { regions: RegionSummary[] }) {
  const [region, setRegion] = useRegionFilter();
  const sorted = [...regions].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <label className="region-filter">
      <span>{t.control.regionFilter.label}</span>
      <select
        value={region}
        onChange={(e) => setRegion(e.target.value)}
        aria-label={t.control.regionFilter.label}
      >
        <option value="">{t.control.regionFilter.all}</option>
        {sorted.map((r) => (
          <option key={r.code} value={r.code}>
            {r.name}
          </option>
        ))}
      </select>
    </label>
  );
}
