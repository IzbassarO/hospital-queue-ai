/** Scene 5 — TRUST: six properties of the accepted system; identities behind technical provenance. */
import { Link } from "react-router-dom";
import { useAssurance, useOperationalOverview } from "../../api/operational";
import { t } from "../../i18n";
import { fmtDate } from "../../lib/format";
import { useReviewOverview } from "../api";
import { capabilityName, percent0, statusLabel } from "../language";
import { Panel, Scene, Technical } from "../primitives";
import { EvidenceState } from "./SubjectState";

export function TrustScene() {
  const assurance = useAssurance();
  const overview = useOperationalOverview();
  const review = useReviewOverview();
  return (
    <Scene
      kicker={t.demo.scenes.trust.kicker}
      title={t.demo.trust.title}
      lead={<p className="scene-sub">{t.demo.trust.subtitle}</p>}
    >
      <EvidenceState
        isPending={assurance.isPending}
        error={assurance.error}
        data={assurance.data}
        notPublished={t.tower.noPublicationHint}
      >
        {(a) => {
          const byId = Object.fromEntries(a.capabilities.map((c) => [c.id, c]));
          const accepted = a.capabilities.filter(
            (c) => c.status === "ACCEPTED",
          ).length;
          const rejected = a.capabilities.filter(
            (c) => c.status === "REJECTED",
          ).length;
          const evaluation = a.capabilities.filter(
            (c) => c.consumption === t.tower.status.EVALUATION_ONLY,
          ).length;
          const calibration = calibrationCoverage(
            byId.flow_temporal_calibration?.evidence,
          );
          const snapshot = overview.data?.snapshot;
          const indicators = [
            {
              key: "temporal",
              title: t.demo.trust.indicators.temporal.title,
              body: t.demo.trust.indicators.temporal.body,
              icon: "◷",
            },
            {
              key: "calibration",
              title: t.demo.trust.indicators.calibration.title,
              body: calibration
                ? t.demo.trust.indicators.calibration.body(
                    calibration.validation,
                    calibration.final,
                  )
                : t.demo.trust.indicators.calibration.bodyUnknown,
              icon: "◫",
            },
            {
              key: "hierarchy",
              title: t.demo.trust.indicators.hierarchy.title,
              body: t.demo.trust.indicators.hierarchy.body,
              icon: "⌂",
            },
            {
              key: "versioned",
              title: t.demo.trust.indicators.versioned.title,
              body: snapshot
                ? t.demo.trust.indicators.versioned.body(
                    snapshot.published,
                    fmtDate(snapshot.origin),
                  )
                : t.demo.loading,
              icon: "⎘",
            },
            {
              key: "separation",
              title: t.demo.trust.indicators.separation.title,
              body: t.demo.trust.indicators.separation.body(
                accepted,
                rejected,
                evaluation,
              ),
              icon: "⊘",
            },
            {
              key: "human",
              title: t.demo.trust.indicators.human.title,
              body: t.demo.trust.indicators.human.body,
              icon: "☺",
            },
          ];
          return (
            <>
              <div className="trust-grid">
                {indicators.map((item, i) => (
                  <article
                    key={item.key}
                    className="trust-card"
                    style={{ animationDelay: `${i * 70}ms` }}
                  >
                    <span className="trust-icon" aria-hidden="true">
                      {item.icon}
                    </span>
                    <h2>{item.title}</h2>
                    <p>{item.body}</p>
                  </article>
                ))}
              </div>
              <div className="trust-foot">
                <Panel tone="glass" className="trust-lineage">
                  <p className="panel-eyebrow">
                    {t.demo.trust.indicators.lineage.title}
                  </p>
                  <p>{t.demo.trust.indicators.lineage.body}</p>
                  <p className="trust-frozen">
                    {a.snapshot.frozen
                      ? t.demo.trust.frozen
                      : t.demo.trust.notFrozen}
                  </p>
                  <Link to="/assurance" className="btn-ghost">
                    {t.demo.trust.openAssurance} →
                  </Link>
                </Panel>
                <Technical
                  title={t.demo.trust.provenance}
                  items={[
                    {
                      label: t.demo.trust.assurance,
                      value: `${a.snapshot.id} · ${a.snapshot.identity}`,
                    },
                    ...(snapshot
                      ? [
                          {
                            label: t.demo.trust.publication,
                            value: `${snapshot.id} · ${snapshot.identity}`,
                          },
                        ]
                      : []),
                    ...(review.data
                      ? [
                          {
                            label: t.demo.trust.review,
                            value: `${review.data.snapshot.publication_id} · ${review.data.snapshot.publication_identity_sha256}`,
                          },
                        ]
                      : []),
                    ...a.snapshot.facts,
                    ...(snapshot
                      ? snapshot.facts
                          .filter((f) => f.label.includes("dataset"))
                          .slice(0, 1)
                      : []),
                  ]}
                  lines={a.capabilities.map(
                    (c) =>
                      `${capabilityName(c.id)} (${c.id}) · ${statusLabel(c.status)} · ${c.acceptance} · ${c.consumption} · ${byId[c.id]?.freshness ?? ""}`,
                  )}
                />
              </div>
            </>
          );
        }}
      </EvidenceState>
    </Scene>
  );
}

function calibrationCoverage(
  evidence: Record<string, unknown> | undefined,
): { validation: string; final: string } | null {
  const nested = evidence?.calibration_evidence;
  if (typeof nested !== "object" || nested === null) return null;
  const v = (nested as Record<string, unknown>)
    .hospital_registrations_validation_coverage;
  const f = (nested as Record<string, unknown>)
    .hospital_registrations_final_coverage;
  if (typeof v !== "number" || typeof f !== "number") return null;
  return { validation: percent0(v), final: percent0(f) };
}
