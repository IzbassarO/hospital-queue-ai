/** Scene 2 — UNDERSTAND: the forecast, its calibrated uncertainty and three human-readable blocks. */
import { useState } from "react";
import { useExplanation } from "../../api/operational";
import { t } from "../../i18n";
import { fmtDate } from "../../lib/format";
import { useObservedHistory } from "../api";
import { ForecastStory } from "../charts/ForecastStory";
import { DemoEvidenceDrawer } from "./DemoEvidenceDrawer";
import { reasonLabel, translateList } from "../language";
import { Bullets, NonClaims, Panel, Scene, Technical } from "../primitives";
import { SubjectState } from "./SubjectState";
import { useDemoSubject } from "../useDemoSubject";

export function UnderstandScene() {
  const subject = useDemoSubject();
  const [explain, setExplain] = useState(false);
  const signal = subject.signal;
  const explanation = useExplanation(signal?.id ?? "");
  const observed = useObservedHistory(
    signal?.org ?? null,
    signal?.profile ?? null,
    signal?.origin ?? "",
  );
  return (
    <SubjectState subject={subject}>
      {(s) => {
        const series = subject.series;
        const coverage =
          series?.points.find((p) => p.interval !== null)?.coverage ?? null;
        const why = translateList(explanation.data?.why ?? []);
        const reasons = [
          ...new Set([...s.reasons.map(reasonLabel), ...why.human]),
        ];
        const knows = [
          s.support === "DIRECT_SUPPORTED"
            ? t.demo.understand.knows.support
            : s.support === "FALLBACK_LIMITED"
              ? t.demo.understand.knows.supportFallback
              : t.demo.understand.knows.supportNone,
          s.rawInterval && coverage
            ? t.demo.understand.knows.calibrated(coverage)
            : t.demo.understand.knows.notCalibrated,
          t.demo.understand.knows.horizon,
          t.demo.understand.knows.hierarchy,
          t.demo.understand.knows.history,
          ...(s.rawDataFreshness
            ? [t.demo.understand.knows.dataAsOf(fmtDate(s.rawDataFreshness))]
            : []),
        ];
        return (
          <Scene
            kicker={t.demo.scenes.understand.kicker}
            title={t.demo.understand.title}
            lead={
              <p className="scene-sub">
                {subject.names.hospital} · {subject.names.profile} ·{" "}
                {t.demo.origin}: {fmtDate(s.origin)}
              </p>
            }
          >
            <div className="scene-grid understand-grid">
              <Panel
                tone="glass"
                className="understand-chart"
                title={t.demo.understand.chartTitle}
              >
                {series ? (
                  <ForecastStory
                    observed={observed.data ?? []}
                    forecast={series.points.map((p) => ({
                      date: p.date,
                      central: p.central,
                      interval: p.interval,
                    }))}
                    threshold={s.rawThreshold ?? null}
                    crossing={s.rawCrossing ?? null}
                    coverage={coverage}
                  />
                ) : subject.forecastQuery.isPending ? (
                  <p role="status" className="scene-state">
                    {t.demo.loading}
                  </p>
                ) : (
                  <p role="status" className="scene-state">
                    {t.tower.noForecast}
                  </p>
                )}
                <p className="chart-note">
                  {observed.data?.length
                    ? `${t.demo.understand.observed} — ${t.demo.understand.observedSource}.`
                    : observed.isError
                      ? t.demo.understand.noObserved
                      : ""}{" "}
                  {t.demo.understand.horizon(series?.points.length ?? 14)}.
                </p>
              </Panel>
              <div className="understand-blocks">
                <Panel tone="paper" eyebrow={t.demo.understand.whyTitle}>
                  <Bullets items={reasons} tone="check" />
                </Panel>
                <Panel eyebrow={t.demo.understand.knowsTitle}>
                  <Bullets items={knows} />
                </Panel>
                <NonClaims
                  title={t.demo.understand.notClaimTitle}
                  items={t.demo.understand.notClaims}
                />
                <div className="understand-actions">
                  <button
                    type="button"
                    className="btn-accent"
                    onClick={() => setExplain(true)}
                  >
                    {t.demo.understand.evidenceDrawer}
                  </button>
                </div>
                <section
                  className="ask-slot"
                  aria-label={t.demo.understand.askTitle}
                >
                  <div className="ask-head">
                    <span className="ask-title">
                      {t.demo.understand.askTitle}
                    </span>
                    <span className="ask-badge">
                      {t.demo.understand.askBadge}
                    </span>
                  </div>
                  <p>{t.demo.understand.askSoon}</p>
                </section>
              </div>
            </div>
            <div className="scene-foot">
              <Technical
                title={t.demo.understand.technical}
                items={[
                  { label: "Series ID", value: s.seriesId },
                  { label: t.tower.reasons, value: s.reasons.join(", ") },
                  {
                    label: t.tower.materiality,
                    value: s.rawMateriality ?? t.common.noData,
                  },
                  ...(series ? series.provenance : []),
                ]}
                lines={[...s.evidence, ...why.technical]}
              />
            </div>
            {explain ? (
              <DemoEvidenceDrawer
                key={s.id}
                signalId={s.id}
                identity={s.identity}
                onClose={() => setExplain(false)}
              />
            ) : null}
          </Scene>
        );
      }}
    </SubjectState>
  );
}
