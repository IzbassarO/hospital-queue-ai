/** Scene 3 — TEST: accepted non-causal forecast stress tests, baseline versus scenario. */
import { useState } from "react";
import { t } from "../../i18n";
import { fmtDate, fmtNumber } from "../../lib/format";
import { useStressTest, type StressOutcome } from "../api";
import { StressChart } from "../charts/StressChart";
import { percent1, severityLabel, translateSentence } from "../language";
import {
  Arrow,
  Bullets,
  NonClaims,
  Panel,
  Scene,
  SeverityPill,
  Stat,
  StatGrid,
  Technical,
} from "../primitives";
import { EvidenceState, SubjectState } from "./SubjectState";
import { useDemoSubject } from "../useDemoSubject";

export function TestScene() {
  const subject = useDemoSubject();
  const stress = useStressTest(subject.signal?.id ?? "");
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <SubjectState subject={subject}>
      {(s) => (
        <Scene
          kicker={t.demo.scenes.test.kicker}
          title={t.demo.test.title}
          lead={
            <p className="scene-sub" data-nonclaim="true">
              {t.demo.test.subtitle}
            </p>
          }
        >
          <EvidenceState
            isPending={stress.isPending}
            error={stress.error}
            data={stress.data}
            notPublished={t.demo.test.notPublished}
          >
            {(data) => {
              const outcomes = data.outcomes;
              const stressed = outcomes.filter(
                (o) => o.scenario.scenario_type !== "identity",
              );
              const identity = outcomes.find(
                (o) => o.scenario.scenario_type === "identity",
              );
              const active: StressOutcome | undefined =
                stressed.find((o) => o.scenario.scenario_id === selected) ??
                stressed.at(-1) ??
                identity;
              if (!active) return null;
              const multiplier = active.scenario.multiplier;
              const label =
                multiplier == null
                  ? t.demo.test.identity
                  : t.demo.test.multiplier(multiplier);
              const network = active.scenario.network_summary;
              return (
                <>
                  <div
                    className="scenario-bar"
                    role="group"
                    aria-label={t.demo.test.scenario}
                  >
                    {identity ? (
                      <span className="scenario-identity">
                        <span className="check" aria-hidden="true">
                          ✓
                        </span>
                        {t.demo.test.identity}: {t.demo.test.identityHint}
                      </span>
                    ) : null}
                    <div className="scenario-chips">
                      {stressed.map((o) => (
                        <button
                          key={o.scenario.scenario_id}
                          type="button"
                          className={`chip ${o.scenario.scenario_id === active.scenario.scenario_id ? "is-active" : ""}`}
                          aria-pressed={
                            o.scenario.scenario_id ===
                            active.scenario.scenario_id
                          }
                          onClick={() => setSelected(o.scenario.scenario_id)}
                        >
                          {t.demo.test.multiplier(o.scenario.multiplier ?? 1)}
                        </button>
                      ))}
                    </div>
                    {multiplier != null ? (
                      <span className="scenario-hint">
                        {t.demo.test.scenarioHint(multiplier)}
                      </span>
                    ) : null}
                  </div>
                  <div className="scene-grid test-grid">
                    <Panel
                      tone="glass"
                      title={`${t.demo.test.chartTitle} · ${label}`}
                    >
                      <StressChart
                        key={active.scenario.scenario_id}
                        cells={active.cells}
                        scenarioLabel={label}
                        isIdentity={
                          active.scenario.scenario_type === "identity"
                        }
                      />
                      <p className="chart-note">
                        {t.demo.test.sensitivity}: {t.demo.test.sensitivityHint}
                        . {t.demo.test.scope}: {t.demo.test.scopeAll}.
                      </p>
                    </Panel>
                    <div className="test-side">
                      <Panel
                        eyebrow={t.demo.test.outcomeTitle}
                        title={`${subject.names.hospital} · ${subject.names.profile}`}
                      >
                        <div className="before-after">
                          <div>
                            <span className="ba-label">
                              {t.demo.test.severityBefore}
                            </span>
                            <SeverityPill
                              value={active.baseline_severity}
                              size="lg"
                            />
                          </div>
                          <Arrow />
                          <div>
                            <span className="ba-label">
                              {t.demo.test.severityAfter}
                            </span>
                            <SeverityPill
                              value={active.scenario_severity}
                              size="lg"
                            />
                          </div>
                        </div>
                        <StatGrid>
                          <Stat
                            label={t.demo.test.central}
                            text={`${fmtNumber(active.baseline_central, 1)} → ${fmtNumber(active.scenario_central, 1)}`}
                            hint={
                              active.relative_delta === null ||
                              active.relative_delta === 0
                                ? t.demo.test.unchanged
                                : `${active.relative_delta > 0 ? "+" : "−"}${percent1(Math.abs(active.relative_delta))}`
                            }
                          />
                          <Stat
                            label={t.demo.test.rank}
                            text={`${active.baseline_inbox_rank == null ? "—" : `#${active.baseline_inbox_rank}`} → ${active.scenario_inbox_rank == null ? "—" : `#${active.scenario_inbox_rank}`}`}
                          />
                          <Stat
                            label={t.demo.test.crossing}
                            text={
                              active.first_crossing_date
                                ? fmtDate(active.first_crossing_date)
                                : t.common.noData
                            }
                          />
                          <Stat
                            label={t.demo.understand.threshold}
                            value={active.threshold_value}
                            unit={t.demo.detect.perDay}
                          />
                        </StatGrid>
                        {active.scenario_reason ? (
                          <p className="outcome-reason">
                            {translateSentence(active.scenario_reason) ??
                              severityLabel(active.scenario_severity)}
                          </p>
                        ) : null}
                      </Panel>
                      <Panel
                        eyebrow={t.demo.test.networkTitle}
                        title={t.demo.test.networkHint}
                      >
                        <Bullets
                          items={[
                            t.demo.test.networkCells(
                              percent1(network.severity_changed_share),
                              fmtNumber(network.severity_changed_count, 0),
                            ),
                            t.demo.test.networkEntities(
                              fmtNumber(
                                network.entity_severity_changed_count,
                                0,
                              ),
                              fmtNumber(network.entity_count, 0),
                            ),
                          ]}
                        />
                      </Panel>
                      <NonClaims
                        title={t.demo.understand.notClaimTitle}
                        items={t.demo.test.nonClaims}
                      />
                    </div>
                  </div>
                  <div className="scene-foot">
                    <Technical
                      title={t.demo.understand.technical}
                      items={[
                        {
                          label: "Scenario",
                          value: active.scenario.scenario_id,
                        },
                        {
                          label: "Classification",
                          value: active.scenario.classification,
                        },
                        {
                          label: "Range",
                          value: `${active.scenario.uncertainty_label} · ${active.scenario.uncertainty_method}`,
                        },
                        {
                          label: "Publication",
                          value: data.snapshot.publication_id,
                        },
                        {
                          label: "Publication SHA256",
                          value: data.snapshot.publication_identity_sha256,
                        },
                        {
                          label: "Operational SHA256",
                          value:
                            data.snapshot
                              .operational_publication_identity_sha256,
                        },
                        ...Object.entries(data.snapshot.source_provenance).map(
                          ([key, p]) => ({
                            label: `${key} · run`,
                            value: p.run_id,
                          }),
                        ),
                      ]}
                      lines={[
                        ...(active.scenario.evidence_facts ?? []),
                        ...(active.scenario.limitations ?? []),
                        ...(active.limitations ?? []),
                      ]}
                    />
                  </div>
                  {s.identity !==
                  data.snapshot.operational_publication_identity_sha256 ? (
                    <p className="notice-dark" role="status">
                      {t.tower.publicationChanged}
                    </p>
                  ) : null}
                </>
              );
            }}
          </EvidenceState>
        </Scene>
      )}
    </SubjectState>
  );
}
