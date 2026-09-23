import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useSignal } from "../api/operational";
import { PageHeader } from "../components/PageHeader";
import {
  EvidenceState,
  Facts,
  Limitations,
  Lines,
  Notice,
  Provenance,
  SeverityBadge,
  SupportBadge,
} from "../components/control/Evidence";
import { SubjectLinks } from "../components/control/SignalList";
import { ExplanationDrawer } from "../components/control/ExplanationDrawer";
import { ForecastPanel } from "../components/control/ForecastChart";
import { t } from "../i18n";

export function SignalPage() {
  const { signalId = "" } = useParams();
  const query = useSignal(signalId);
  const [explain, setExplain] = useState(false);
  return (
    <div className="space-y-6 page-reveal">
      <Link className="link" to="/signals">
        ← {t.tower.returnSignals}
      </Link>
      <EvidenceState query={query}>
        {(s) => (
          <>
            <PageHeader title={s.headline}>
              <p className="text-muted">
                {s.typeLabel} · {t.tower.rank}: {s.rank ?? t.tower.unranked}
              </p>
            </PageHeader>
            <SubjectLinks signal={s} />
            <div className="flex flex-wrap items-center gap-3">
              <SeverityBadge value={s.severity} />
              <SupportBadge value={s.support} />
              <button
                className="btn btn-primary"
                onClick={() => setExplain(true)}
              >
                {t.tower.explain}
              </button>
            </div>
            <p className="text-lg">{s.reason}</p>
            {s.support !== "DIRECT_SUPPORTED" ? (
              <Notice>
                {t.tower.support}:{" "}
                {s.support === "UNSUPPORTED"
                  ? t.tower.status.UNSUPPORTED
                  : t.tower.status.FALLBACK_LIMITED}{" "}
                · {t.tower.fallback}: {s.fallback}
              </Notice>
            ) : null}
            <section className="card p-5 space-y-4">
              <h2 className="text-xl font-semibold">{t.tower.evidence}</h2>
              <Facts
                items={[
                  { label: t.tower.forecast, value: s.forecast },
                  { label: t.tower.interval, value: s.interval },
                  { label: t.tower.uncertainty, value: s.uncertainty },
                  { label: t.tower.fallback, value: s.fallback },
                  ...s.facts,
                ]}
              />
              {s.pressure ? <Notice>{t.tower.pressureHint}</Notice> : null}
              <Lines items={s.evidence} />
              <h3 className="font-semibold">{t.tower.reasons}</h3>
              <Lines items={s.reasons} />
            </section>
            <ForecastPanel
              key={`${s.id}:${s.identity}`}
              identity={s.identity}
              seriesId={s.seriesId}
              filters={{
                origin: s.origin,
                org: s.org,
                region: s.region,
                profile: s.profile,
                target: s.target,
                level: s.org ? "hospital" : s.region ? "region" : "national",
              }}
            />
            <Limitations items={s.limitations} />
            <Provenance items={s.provenance} />
            {explain ? (
              <ExplanationDrawer
                key={s.id}
                signalId={s.id}
                identity={s.identity}
                onClose={() => setExplain(false)}
              />
            ) : null}
          </>
        )}
      </EvidenceState>
    </div>
  );
}
