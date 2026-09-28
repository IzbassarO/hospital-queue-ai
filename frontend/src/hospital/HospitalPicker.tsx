/**
 * Choosing the hospital: search by name, filter by region, pick from the list.
 *
 * Hospitals with fewer than 20 waiting referrals are out of the default list — not hidden. One checkbox brings
 * them back, and every one of them carries the "мало данных" tag in the row itself, so a thin queue can never be
 * read as a full one.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { t } from "../i18n";
import { fmtNumber } from "../lib/format";
import type { WaitingHospital } from "../api/waiting-list";

const norm = (value: string) =>
  value.toLocaleLowerCase("ru").replace(/ё/g, "е");

export function HospitalPicker({
  hospitals,
  regions,
}: {
  hospitals: WaitingHospital[];
  regions: { code: string; name: string }[];
}) {
  const [query, setQuery] = useState("");
  const [region, setRegion] = useState("");
  const [withSmall, setWithSmall] = useState(false);

  const found = useMemo(() => {
    const needle = norm(query.trim());
    return hospitals.filter((h) => {
      if (region && h.region_code !== region) return false;
      if (!withSmall && h.support_class === "SPARSE") return false;
      return !needle || norm(h.org_name).includes(needle);
    });
  }, [hospitals, query, region, withSmall]);

  return (
    <section className="hos-pick" aria-label={t.hospital.pick.title}>
      <div className="block-head">
        <h2>{t.hospital.pick.title}</h2>
        <p>{t.hospital.pick.mapHint}</p>
      </div>
      <div className="hos-pick-controls">
        <div className="hos-field">
          <label htmlFor="hos-search">{t.hospital.pick.search}</label>
          <input
            id="hos-search"
            type="search"
            value={query}
            placeholder={t.hospital.pick.searchPlaceholder}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="hos-field">
          <label htmlFor="hos-region">{t.hospital.pick.region}</label>
          <select
            id="hos-region"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
          >
            <option value="">{t.hospital.pick.allRegions}</option>
            {regions.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        <label className="hos-check">
          <input
            type="checkbox"
            checked={withSmall}
            onChange={(e) => setWithSmall(e.target.checked)}
          />
          <span>{t.hospital.pick.showSmall}</span>
        </label>
      </div>
      <p className="hos-pick-count" role="status">
        {t.hospital.pick.found(found.length)}
        {withSmall ? ` · ${t.hospital.pick.smallHint}` : ""}
      </p>
      {found.length === 0 ? (
        <div className="hos-empty" role="status">
          <h3>{t.hospital.pick.empty}</h3>
          <p>{t.hospital.pick.emptyHint}</p>
        </div>
      ) : (
        <ul className="hos-list" role="list">
          {found.slice(0, 120).map((h) => (
            <li key={h.org_code}>
              <Link to={`/hospital/${h.org_code}`} className="hos-row">
                <span className="hos-row-name">{h.org_name}</span>
                <span className="hos-row-meta">
                  {h.region_name}
                  {h.support_class === "SPARSE" ? (
                    <em className="hos-thin">{t.hospital.pick.smallTag}</em>
                  ) : null}
                </span>
                <span className="hos-row-count">
                  <b>{fmtNumber(h.waiting_count, 0)}</b>
                  <small>{t.hospital.header.waiting}</small>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
