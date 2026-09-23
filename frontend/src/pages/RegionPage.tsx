import { Link, useParams, useSearchParams } from "react-router-dom";
import { useOperationalRegion, useSignals } from "../api/operational";
import { useDictionaries } from "../api/queries";
import { PageHeader, Section } from "../components/PageHeader";
import {
  EvidenceState,
  Publication,
  Summary,
} from "../components/control/Evidence";
import { SignalList } from "../components/control/SignalList";
import { ForecastPanel } from "../components/control/ForecastChart";
import { t } from "../i18n";

export function RegionPage() {
  const { code = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const profile = params.get("profile") || undefined;
  const query = useOperationalRegion(code);
  const dictionaries = useDictionaries();
  const signals = useSignals({ region: code, profile, limit: 10, offset: 0 });
  return (
    <div className="space-y-6 page-reveal">
      <PageHeader
        title={
          dictionaries.data?.regions.find((r) => r.code === code)?.name ??
          `${t.tower.region} ${code}`
        }
        crumbs={[{ label: t.tower.overview, to: "/" }, { label: code }]}
      />
      <EvidenceState query={query}>
        {(d) => (
          <>
            <Publication snapshot={d.snapshot} />
            <Summary counts={d.counts} />
            <p className="text-sm text-muted">
              {t.tower.forecastPoints}: {d.forecastCount}
            </p>
            <div className="max-w-lg">
              <label
                className="mb-1 block text-sm font-medium"
                htmlFor="region-profile"
              >
                {t.tower.profile}
              </label>
              <select
                id="region-profile"
                className="field"
                value={profile ?? ""}
                onChange={(e) =>
                  setParams(e.target.value ? { profile: e.target.value } : {})
                }
              >
                <option value="">{t.tower.all}</option>
                {profile &&
                !dictionaries.data?.profiles.some((p) => p.code === profile) ? (
                  <option value={profile}>{profile}</option>
                ) : null}
                {dictionaries.data?.profiles.map((p) => (
                  <option value={p.code} key={p.code}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <Section
              title={t.tower.priority}
              caption={t.tower.rankHint}
              id="region-signals"
              actions={
                <Link
                  className="link"
                  to={`/signals?${new URLSearchParams({ region: code, ...(profile ? { profile } : {}) })}`}
                >
                  {t.tower.showAll}
                </Link>
              }
            >
              <EvidenceState query={signals}>
                {(s) => (
                  <SignalList
                    signals={s.items}
                    identity={d.snapshot.identity}
                  />
                )}
              </EvidenceState>
            </Section>
            <ForecastPanel
              key={`${code}:${profile}:${d.snapshot.identity}`}
              identity={d.snapshot.identity}
              filters={{
                level: "region",
                region: code,
                profile,
                origin: d.snapshot.origin,
              }}
            />
          </>
        )}
      </EvidenceState>
    </div>
  );
}
