import { Link, useParams } from "react-router-dom";
import { useOperationalHospital } from "../../api/operational";
import { useDictionaries } from "../../api/queries";
import { PageHeader, Section } from "../../components/PageHeader";
import {
  EvidenceState,
  Notice,
  Publication,
  Summary,
} from "../../components/control/Evidence";
import { SignalList, SubjectLinks } from "../../components/control/SignalList";
import { ForecastPanel } from "../../components/control/ForecastChart";
import { t } from "../../i18n";

export function HospitalPage() {
  const { org = "", profile = "" } = useParams();
  const query = useOperationalHospital(org, profile);
  const dictionaries = useDictionaries();
  const profileName =
    dictionaries.data?.profiles.find((p) => p.code === profile)?.name ??
    profile;
  return (
    <div className="space-y-6 page-reveal">
      <PageHeader
        title={`${t.tower.hospital} ${org} · ${profileName}`}
        crumbs={[
          { label: t.tower.overview, to: "/" },
          { label: org },
          { label: profile },
        ]}
      />
      <EvidenceState query={query}>
        {(d) => (
          <>
            <SubjectLinks
              signal={{ org: d.org, profile: d.profile, region: d.region }}
            />
            <Publication snapshot={d.snapshot} />
            <Summary counts={d.counts} />
            <Notice>{t.tower.pressureHint}</Notice>
            <Section
              title={t.tower.signals}
              caption={t.tower.rankHint}
              id="hospital-signals"
            >
              <SignalList signals={d.signals} identity={d.snapshot.identity} />
              {d.signals.length < d.counts.total ? (
                <>
                  <Notice>{t.tower.partial}</Notice>
                  <Link
                    className="link"
                    to={`/signals?${new URLSearchParams({ org, profile })}`}
                  >
                    {t.tower.showAll}
                  </Link>
                </>
              ) : null}
            </Section>
            <p className="text-sm text-muted">
              {t.tower.forecastPoints}: {d.forecastCount}
            </p>
            <ForecastPanel
              key={`${org}:${profile}:${d.snapshot.identity}`}
              identity={d.snapshot.identity}
              filters={{
                level: "hospital",
                org,
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
