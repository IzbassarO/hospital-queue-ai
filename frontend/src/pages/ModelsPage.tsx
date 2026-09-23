import { useAssurance } from "../api/operational";
import { label } from "../api/operational-adapters";
import { PageHeader } from "../components/PageHeader";
import {
  EvidenceState,
  Empty,
  Facts,
  Limitations,
  Lines,
  Notice,
  Provenance,
} from "../components/control/Evidence";
import { t } from "../i18n";

export function ModelsPage() {
  const query = useAssurance();
  return (
    <div className="space-y-6 page-reveal">
      <PageHeader title={t.tower.assurance}>
        <p className="text-muted">
          {t.tower.human} · {t.tower.noAutonomy}
        </p>
      </PageHeader>
      <EvidenceState query={query}>
        {(d) => (
          <>
            <div className="card p-5 space-y-3">
              <p className="eyebrow">
                {d.snapshot.frozen ? t.tower.frozen : t.tower.status.UNKNOWN}
              </p>
              <p>
                {t.tower.published}: {d.snapshot.published}
              </p>
              <Provenance items={d.snapshot.facts} />
            </div>
            {d.capabilities.length === 0 ? (
              <Empty>{t.tower.noCapabilities}</Empty>
            ) : (
              <div className="assurance-grid">
                {d.capabilities.map((c) => (
                  <article
                    id={c.id}
                    key={c.id}
                    className="card capability-card space-y-4 p-5"
                    aria-labelledby={`cap-${c.id}`}
                  >
                    <header className="space-y-2">
                      <p className="eyebrow">{c.id}</p>
                      <h2 id={`cap-${c.id}`} className="text-xl font-semibold">
                        {c.title}
                      </h2>
                      <span
                        className={`evidence-badge evidence-${c.status.toLowerCase()}`}
                      >
                        {label(c.status)}
                      </span>
                    </header>
                    <Facts
                      items={[
                        { label: t.tower.acceptance, value: c.acceptance },
                        { label: t.tower.consumption, value: c.consumption },
                        {
                          label: t.tower.support,
                          value: c.support.join(" · "),
                        },
                        {
                          label: t.tower.freshness,
                          value: `${c.freshness} · ${c.freshnessReason}`,
                        },
                      ]}
                    />
                    {c.range.length ? (
                      <p className="text-sm">{c.range.join(" · ")}</p>
                    ) : null}
                    {c.id === "decision_alternatives" ? (
                      <Notice>{t.tower.alternatives}</Notice>
                    ) : null}
                    <section>
                      <h3 className="mb-2 font-semibold">
                        {t.tower.governance}
                      </h3>
                      <Lines items={c.governance} />
                    </section>
                    <Limitations items={c.limitations} />
                    {c.claims.length ? (
                      <details>
                        <summary>{t.tower.evidence}</summary>
                        <Lines items={c.claims} />
                      </details>
                    ) : null}
                    <Provenance items={c.identities} />
                  </article>
                ))}
              </div>
            )}
          </>
        )}
      </EvidenceState>
    </div>
  );
}
