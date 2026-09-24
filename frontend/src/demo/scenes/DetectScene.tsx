/** Scene 1 — DETECT: one real signal, understandable in ten seconds. */
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { t } from "../../i18n";
import { fmtDate, fmtNumber } from "../../lib/format";
import { RegionBars } from "../charts/RegionBars";
import { DemoEvidenceDrawer } from "./DemoEvidenceDrawer";
import { scenePath } from "../journey";
import { number1, severityAdjective, statusLabel } from "../language";
import {
  FactLine,
  NonClaims,
  Panel,
  Scene,
  SeverityPill,
  Stat,
  StatGrid,
  Technical,
} from "../primitives";
import { SubjectState } from "./SubjectState";
import { hospitalName, useDemoSubject } from "../useDemoSubject";

export function DetectScene() {
  const subject = useDemoSubject();
  const location = useLocation();
  const [explain, setExplain] = useState(false);
  return (
    <SubjectState subject={subject}>
      {(signal) => {
        const lead = t.demo.detect.lead(signal.rawLeadDays ?? null);
        const coverage =
          subject.series?.points.find((p) => p.interval !== null)?.coverage ??
          null;
        const regionCounts = subject.region?.counts;
        return (
          <Scene
            kicker={t.demo.scenes.detect.kicker}
            title={t.demo.detect.title}
            lead={
              <p className="scene-headline" data-headline="true">
                {t.demo.detect.headline(
                  severityAdjective[signal.severity] ??
                    signal.severity.toLowerCase(),
                  lead,
                )}
              </p>
            }
            aside={<SeverityPill value={signal.severity} size="lg" />}
          >
            <div className="scene-grid detect-grid">
              <div className="detect-left">
                <Panel tone="glass" className="detect-subject">
                  <dl className="subject-facts">
                    <div>
                      <dt>{t.demo.detect.hospital}</dt>
                      <dd className="subject-primary">
                        {subject.names.hospital}
                      </dd>
                    </div>
                    <div>
                      <dt>{t.demo.detect.profile}</dt>
                      <dd>{subject.names.profile}</dd>
                    </div>
                    <div>
                      <dt>{t.demo.detect.region}</dt>
                      <dd>{subject.names.region}</dd>
                    </div>
                    <div>
                      <dt>{t.demo.detect.horizon}</dt>
                      <dd>
                        {t.demo.detect.horizonValue(
                          signal.rawLeadDays ?? null,
                          signal.rawCrossing
                            ? fmtDate(signal.rawCrossing)
                            : t.common.noData,
                        )}
                      </dd>
                    </div>
                  </dl>
                  <StatGrid>
                    <Stat
                      label={t.demo.detect.central}
                      value={signal.rawForecast}
                      unit={t.demo.detect.perDay}
                      emphasis
                    />
                    <Stat
                      label={t.demo.detect.interval}
                      text={
                        signal.rawInterval
                          ? `${number1(signal.rawInterval[0])} – ${number1(signal.rawInterval[1])}`
                          : t.tower.noInterval
                      }
                      hint={
                        coverage
                          ? t.demo.detect.intervalHint(coverage)
                          : undefined
                      }
                    />
                    <Stat
                      label={t.demo.detect.reference}
                      value={signal.rawThreshold}
                      unit={t.demo.detect.perDay}
                      hint={t.demo.detect.referenceHint}
                    />
                    <Stat
                      label={t.demo.detect.rank}
                      text={
                        signal.rank == null
                          ? t.tower.unranked
                          : `#${signal.rank}`
                      }
                      hint={t.demo.detect.rankHint}
                    />
                  </StatGrid>
                  <div className="detect-actions">
                    <Link
                      to={scenePath("understand", location.search)}
                      className="btn-accent"
                    >
                      {t.demo.detect.why} →
                    </Link>
                    <button
                      type="button"
                      className="btn-ghost"
                      onClick={() => setExplain(true)}
                    >
                      {t.demo.detect.evidence}
                    </button>
                    <span className="support-chip">
                      {t.demo.detect.support}: {statusLabel(signal.support)}
                    </span>
                  </div>
                </Panel>
                <NonClaims
                  title={t.demo.understand.notClaimTitle}
                  items={[t.demo.understand.notClaims[0], t.demo.retrospective]}
                />
              </div>
              <div className="detect-context">
                <Panel
                  eyebrow={t.demo.detect.contextTitle}
                  title={subject.names.region}
                >
                  {regionCounts ? (
                    <FactLine
                      parts={[
                        {
                          value: fmtNumber(regionCounts.total, 0),
                          label: t.demo.detect.regionSignals,
                        },
                        {
                          value: fmtNumber(regionCounts.high, 0),
                          label: t.demo.detect.regionHigh,
                        },
                      ]}
                    />
                  ) : null}
                  {subject.region?.signals.length ? (
                    <ol
                      className="region-rank"
                      aria-label={t.demo.detect.regionTop}
                    >
                      <li className="region-rank-head" aria-hidden="true">
                        {t.demo.detect.regionTop}
                      </li>
                      {subject.region.signals.slice(0, 5).map((s) => (
                        <li
                          key={s.id}
                          className={s.id === signal.id ? "is-subject" : ""}
                        >
                          <span className="rank-badge">#{s.rank ?? "—"}</span>
                          <span className="rank-subject">
                            {hospitalName(
                              subject.dictionaries?.organizations,
                              s.org,
                            )}{" "}
                            ·{" "}
                            {subject.dictionaries?.profiles.find(
                              (p) => p.code === s.profile,
                            )?.name ?? s.profile}
                          </span>
                          <SeverityPill value={s.severity} />
                          {s.id === signal.id ? (
                            <span className="rank-you">
                              {t.demo.detect.thisSignal}
                            </span>
                          ) : null}
                        </li>
                      ))}
                    </ol>
                  ) : null}
                </Panel>
                <Panel eyebrow={t.demo.detect.nationalTitle}>
                  {subject.overview ? (
                    <RegionBars
                      regions={subject.overview.regions.map((r) => ({
                        code: r.code,
                        high: r.counts.high,
                        total: r.counts.total,
                      }))}
                      highlight={signal.region ?? null}
                      names={(code) =>
                        subject.dictionaries?.regions.find(
                          (r) => r.code === code,
                        )?.name ?? code
                      }
                    />
                  ) : null}
                  <p className="footnote">{t.demo.detect.nationalHint}</p>
                </Panel>
              </div>
            </div>
            <div className="scene-foot">
              <Technical
                title={t.demo.understand.technical}
                items={[
                  { label: "Signal ID", value: signal.id },
                  { label: "Series ID", value: signal.seriesId },
                  {
                    label: t.tower.materiality,
                    value: signal.rawMateriality ?? t.common.noData,
                  },
                  { label: t.tower.reasons, value: signal.reasons.join(", ") },
                ]}
              />
            </div>
            {explain ? (
              <DemoEvidenceDrawer
                key={signal.id}
                signalId={signal.id}
                identity={signal.identity}
                onClose={() => setExplain(false)}
              />
            ) : null}
          </Scene>
        );
      }}
    </SubjectState>
  );
}
