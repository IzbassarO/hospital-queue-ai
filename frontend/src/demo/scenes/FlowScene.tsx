/**
 * Scene 0 — FLOW: a finite, step-by-step simulation of one referral's path through the system, from registration to
 * the specialist's decision and the audit trail. Every number on the path is a published or mart value.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  useAssurance,
  useOperationalOverview,
  useSignals,
} from "../../api/operational";
import { useOverview } from "../../api/queries";
import { t } from "../../i18n";
import { fmtDate, fmtNumber } from "../../lib/format";
import { useReviewOverview } from "../api";
import {
  GlyphArrow,
  GlyphAudit,
  GlyphEvidence,
  GlyphFlow,
  GlyphForecast,
  GlyphHuman,
  GlyphPause,
  GlyphPlay,
  GlyphReferral,
  GlyphReplay,
  GlyphSignal,
} from "../glyphs";
import { SCENES, scenePath } from "../journey";
import { severityAdjective } from "../language";
import { useReducedMotion } from "../motion";
import { Facts, Scene, SeverityPill } from "../primitives";
import { useNames } from "../useDemoSubject";

const STEP_MS = 2600;
const SCENE_INDEX = Object.fromEntries(
  SCENES.map((id, i) => [id, i + 1]),
) as Record<(typeof SCENES)[number], number>;
type StepId =
  | "referral"
  | "flow"
  | "forecast"
  | "signal"
  | "evidence"
  | "decision"
  | "audit";
const ORDER: StepId[] = [
  "referral",
  "flow",
  "forecast",
  "signal",
  "evidence",
  "decision",
  "audit",
];
const GLYPHS: Record<StepId, (p: { size?: number }) => ReactNode> = {
  referral: GlyphReferral,
  flow: GlyphFlow,
  forecast: GlyphForecast,
  signal: GlyphSignal,
  evidence: GlyphEvidence,
  decision: GlyphHuman,
  audit: GlyphAudit,
};

interface Metric {
  value: number | null;
  label: string;
  note?: string;
}

export function FlowScene() {
  const reduced = useReducedMotion();
  const location = useLocation();
  const mart = useOverview();
  const operational = useOperationalOverview();
  const ranked = useSignals({ limit: 1, offset: 0 });
  const review = useReviewOverview();
  const assurance = useAssurance();
  const last = ORDER.length - 1;
  const [active, setActive] = useState(reduced ? last : 0);
  const [playing, setPlaying] = useState(!reduced);
  const done = active >= last;

  useEffect(() => {
    if (!playing || reduced || active >= last) return;
    const timer = window.setTimeout(() => setActive((i) => i + 1), STEP_MS);
    return () => window.clearTimeout(timer);
  }, [playing, active, reduced, last]);

  const national = mart.data?.national;
  const snapshot = operational.data?.snapshot;
  const counts = operational.data?.counts;
  const metrics = useMemo<Record<StepId, Metric[]>>(
    () => ({
      referral: [
        {
          value: national?.registrations_28d ?? null,
          label: t.demo.flow.steps.referral.metric,
          note: mart.data
            ? `${t.demo.flow.sourceMart} · ${t.demo.flow.asOf(fmtDate(mart.data.as_of_date))}`
            : undefined,
        },
      ],
      flow: [
        {
          value: national?.n_hospital_profiles ?? null,
          label: t.demo.flow.steps.flow.metric,
        },
        {
          value: national?.n_hospitals ?? null,
          label: t.demo.flow.steps.flow.metric2,
        },
      ],
      forecast: [
        {
          value: snapshot?.forecastCount ?? null,
          label: t.demo.flow.steps.forecast.metric,
          note: snapshot
            ? `${t.demo.flow.sourcePublication} · ${t.demo.flow.origin(fmtDate(snapshot.origin))}`
            : undefined,
        },
      ],
      signal: [
        {
          value: counts?.total ?? null,
          label: t.demo.flow.steps.signal.metric,
        },
        {
          value: counts?.high ?? null,
          label: t.demo.flow.steps.signal.metric2,
        },
      ],
      evidence: [
        {
          value: review.data?.snapshot.scenario_count ?? null,
          label: t.demo.flow.steps.evidence.metric,
        },
        {
          value: review.data?.snapshot.alternative_set_count ?? null,
          label: t.demo.flow.steps.evidence.metric2,
        },
      ],
      decision: [{ value: null, label: t.demo.flow.steps.decision.metric }],
      audit: [
        {
          value: assurance.data?.capabilities.length ?? null,
          label: t.demo.flow.steps.audit.metric,
          note: assurance.data
            ? `${t.tower.published}: ${assurance.data.snapshot.published}`
            : undefined,
        },
      ],
    }),
    [national, mart.data, snapshot, counts, review.data, assurance.data],
  );

  const current = ORDER[active];
  const copy = t.demo.flow.steps[current];
  const progress = active / (ORDER.length - 1);
  const subject = ranked.data?.items[0];
  const names = useNames(subject?.region, subject?.org, subject?.profile);
  return (
    <Scene
      kicker={t.demo.scenes.flow.kicker}
      title={t.demo.flow.title}
      lead={<p className="scene-sub">{t.demo.flow.subtitle}</p>}
    >
      <section
        className={`flow-stage ${done ? "is-done" : ""}`}
        aria-label={t.demo.flow.title}
      >
        <div className="flow-controls">
          <button
            type="button"
            className="btn-lime"
            onClick={() => {
              if (done) {
                setActive(0);
                setPlaying(true);
              } else setPlaying((p) => !p);
            }}
            aria-pressed={playing && !done}
          >
            {done ? (
              <>
                <GlyphReplay /> {t.demo.flow.replay}
              </>
            ) : playing ? (
              <>
                <GlyphPause /> {t.demo.flow.pause}
              </>
            ) : (
              <>
                <GlyphPlay /> {t.demo.flow.play}
              </>
            )}
          </button>
          <span className="flow-step-count" role="status" aria-live="polite">
            {t.demo.flow.step(active + 1, ORDER.length)}
          </span>
        </div>
        <ol
          className="flow-track"
          aria-label={t.demo.flow.stations}
          style={{ ["--progress" as string]: progress }}
        >
          <li className="flow-rail" aria-hidden="true">
            <span className="flow-rail-fill" />
            <span className="flow-runner" />
          </li>
          {ORDER.map((id, i) => {
            const Glyph = GLYPHS[id];
            const state =
              i < active ? "is-past" : i === active ? "is-active" : "is-future";
            return (
              <li
                key={id}
                className={`flow-station ${state} ${id === "decision" ? "is-human" : ""}`}
              >
                <button
                  type="button"
                  className="flow-node"
                  aria-current={i === active ? "step" : undefined}
                  onClick={() => {
                    setPlaying(false);
                    setActive(i);
                  }}
                >
                  <span className="flow-glyph">
                    <Glyph size={20} />
                  </span>
                  <span className="flow-index">{i + 1}</span>
                  <span className="flow-label">
                    {t.demo.flow.steps[id].title}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
        <div className="flow-detail" key={current}>
          <div className="flow-detail-text">
            <p className="flow-detail-kicker">
              {current === "decision" ? (
                <span className="flow-human-tag">
                  <GlyphHuman size={14} /> {t.demo.flow.human}
                </span>
              ) : (
                `${active + 1} · ${copy.title}`
              )}
            </p>
            <h2 className="flow-detail-title">{copy.lead}</h2>
            <p className="flow-detail-body">{copy.detail}</p>
            {current === "signal" && subject ? (
              <Link
                to={scenePath("detect", location.search)}
                className="flow-link"
              >
                {t.demo.detect.why} <GlyphArrow />
              </Link>
            ) : null}
            {current === "decision" ? (
              <Link
                to={scenePath("review", location.search)}
                className="flow-link"
              >
                {t.demo.scenes.review.label} <GlyphArrow />
              </Link>
            ) : null}
          </div>
          <dl className="flow-metrics">
            {metrics[current].map((m) => (
              <div key={m.label} className="flow-metric">
                <dd className="flow-metric-value">
                  {m.value === null ? "—" : fmtNumber(m.value, 0)}
                </dd>
                <dt className="flow-metric-label">{m.label}</dt>
                {m.note ? <dd className="flow-metric-note">{m.note}</dd> : null}
              </div>
            ))}
          </dl>
        </div>
      </section>
      <section className="flow-next" aria-label={t.demo.flow.nextTitle}>
        <Link to={scenePath("detect", location.search)} className="flow-focus">
          <span className="flow-focus-label">{t.demo.flow.subjectKicker}</span>
          <span className="flow-focus-title">
            {subject ? names.hospital : t.demo.loading}
          </span>
          <span className="flow-focus-meta">
            {subject ? `${names.profile} · ${names.region}` : ""}
          </span>
          {subject ? (
            <>
              <span className="flow-focus-row">
                <SeverityPill value={subject.severity} />
                <span className="flow-focus-rank">
                  {t.demo.detect.rank} #{subject.rank ?? "—"}
                </span>
              </span>
              <span className="flow-focus-headline" data-headline="true">
                {t.demo.detect.headline(
                  severityAdjective[subject.severity] ??
                    subject.severity.toLowerCase(),
                  t.demo.detect.lead(subject.rawLeadDays ?? null),
                )}
              </span>
              <Facts
                className="flow-focus-facts"
                rows={[
                  {
                    label: t.demo.detect.central,
                    value:
                      subject.rawForecast == null
                        ? t.common.noData
                        : fmtNumber(subject.rawForecast, 1),
                    hint:
                      subject.rawForecast == null
                        ? undefined
                        : t.demo.detect.perDay,
                  },
                  {
                    label: t.demo.understand.threshold,
                    value:
                      subject.rawThreshold == null
                        ? t.common.noData
                        : fmtNumber(subject.rawThreshold, 1),
                    hint:
                      subject.rawThreshold == null
                        ? undefined
                        : t.demo.detect.perDay,
                  },
                  {
                    label: t.demo.detect.horizon,
                    value: t.demo.detect.horizonValue(
                      subject.rawLeadDays ?? null,
                      subject.rawCrossing
                        ? fmtDate(subject.rawCrossing)
                        : t.common.noData,
                    ),
                  },
                ]}
              />
            </>
          ) : null}
          <span className="flow-focus-cta">
            {t.demo.flow.subjectCta} <GlyphArrow size={14} />
          </span>
        </Link>
        <div className="flow-route">
          <p className="flow-route-title">{t.demo.flow.nextTitle}</p>
          <ol className="flow-route-list">
            {(["detect", "test", "review"] as const).map((id) => (
              <li key={id}>
                <Link
                  to={scenePath(id, location.search)}
                  className="flow-route-item"
                >
                  <span className="flow-route-index">{SCENE_INDEX[id]}</span>
                  <span className="flow-route-text">
                    <span className="flow-route-scene">
                      {t.demo.scenes[id].label}
                    </span>
                    <span className="flow-route-lead">
                      {t.demo.flow.next[id].title}
                    </span>
                    <span className="flow-route-body">
                      {t.demo.flow.next[id].body}
                    </span>
                  </span>
                  <GlyphArrow size={14} />
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </Scene>
  );
}
