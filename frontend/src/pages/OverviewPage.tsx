import { Link } from "react-router-dom";
import { useOperationalOverview, useSignals } from "../api/operational";
import { useDictionaries } from "../api/queries";
import { PageHeader, Section } from "../components/PageHeader";
import {
  EvidenceState,
  Empty,
  Notice,
  Publication,
  Summary,
} from "../components/control/Evidence";
import { SignalList } from "../components/control/SignalList";
import { ForecastPanel } from "../components/control/ForecastChart";
import { t } from "../i18n";
import { regionPath } from "../lib/paths";

export function OverviewPage() {
  const overview = useOperationalOverview();
  const signals = useSignals({ limit: 5, offset: 0 });
  const dictionaries = useDictionaries();
  return (
    <div className="space-y-6 page-reveal">
      <PageHeader title={t.tower.title}>
        <p className="max-w-4xl text-muted">{t.tower.intro}</p>
      </PageHeader>
      <EvidenceState query={overview}>
        {(data) => (
          <>
            <Publication snapshot={data.snapshot} />
            <Summary counts={data.counts} />
            <div className="control-columns">
              <Section title={t.tower.regional} id="regions">
                <p className="text-sm text-muted">{t.tower.totalHint}</p>
                {dictionaries.isError ? (
                  <Notice>{t.tower.namesUnavailable}</Notice>
                ) : null}
                {data.regions.length ? (
                  <div className="card overflow-x-auto">
                    <table className="evidence-table">
                      <caption className="sr-only">{t.tower.regional}</caption>
                      <thead>
                        <tr>
                          {[
                            t.tower.region,
                            t.tower.total,
                            t.tower.high,
                            t.tower.direct,
                          ].map((h) => (
                            <th scope="col" key={h}>
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.regions.map((r) => (
                          <tr key={r.code}>
                            <th scope="row">
                              <Link className="link" to={regionPath(r.code)}>
                                {dictionaries.data?.regions.find(
                                  (d) => d.code === r.code,
                                )?.name ?? r.code}
                              </Link>
                            </th>
                            <td>{r.counts.total}</td>
                            <td>{r.counts.high}</td>
                            <td>{r.counts.direct}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <Empty>{t.tower.noRegions}</Empty>
                )}
              </Section>
              <aside className="card p-5 space-y-3">
                <p className="eyebrow">{t.tower.evidence}</p>
                <h2 className="text-xl font-semibold">{t.tower.pressure}</h2>
                <p>{t.tower.pressureHint}</p>
                <p className="text-sm text-muted">{t.tower.human}</p>
                <Link to="/assurance" className="link">
                  {t.tower.assurance} →
                </Link>
              </aside>
            </div>
            <Section
              title={t.tower.priority}
              caption={t.tower.rankHint}
              id="priority"
              actions={
                <Link className="link" to="/signals">
                  {t.tower.showAll} →
                </Link>
              }
            >
              <EvidenceState query={signals}>
                {(rows) => (
                  <SignalList
                    signals={rows.items}
                    identity={data.snapshot.identity}
                  />
                )}
              </EvidenceState>
            </Section>
            <ForecastPanel
              key={data.snapshot.identity}
              identity={data.snapshot.identity}
              filters={{ level: "national", origin: data.snapshot.origin }}
            />
          </>
        )}
      </EvidenceState>
    </div>
  );
}
