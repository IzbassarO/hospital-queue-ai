import { useState } from "react";
import { Link } from "react-router-dom";
import type { SignalView } from "../../api/operational-adapters";
import { useDictionaries } from "../../api/queries";
import { t } from "../../i18n";
import { hospitalPath, regionPath } from "../../lib/paths";
import { Empty, Facts, Notice, SeverityBadge, SupportBadge } from "./Evidence";
import { ExplanationDrawer } from "./ExplanationDrawer";

export function SubjectLinks({
  signal,
}: {
  signal: Pick<SignalView, "org" | "region" | "profile">;
}) {
  const dictionaries = useDictionaries();
  const regionName =
    dictionaries.data?.regions.find((r) => r.code === signal.region)?.name ??
    signal.region;
  const profileName =
    dictionaries.data?.profiles.find((p) => p.code === signal.profile)?.name ??
    signal.profile;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {signal.region ? (
        <Link className="link" to={regionPath(signal.region)}>
          {t.tower.region}: {regionName}
        </Link>
      ) : null}
      {signal.org && signal.profile ? (
        <Link className="link" to={hospitalPath(signal.org, signal.profile)}>
          {t.tower.hospital}: {signal.org}
        </Link>
      ) : signal.org ? (
        <span>
          {t.tower.hospital}: {signal.org}
        </span>
      ) : null}
      {signal.profile ? (
        <span>
          {t.tower.profile}: {profileName}
        </span>
      ) : null}
    </div>
  );
}
export function SignalList({
  signals,
  identity,
}: {
  signals: SignalView[];
  identity?: string;
}) {
  const [explaining, setExplaining] = useState<SignalView | null>(null);
  if (identity && signals.some((s) => s.identity !== identity))
    return <Notice>{t.tower.publicationChanged}</Notice>;
  return (
    <>
      {signals.length === 0 ? (
        <Empty>{t.tower.noSignals}</Empty>
      ) : (
        <ol className="space-y-3">
          {signals.map((signal) => (
            <li key={signal.id}>
              <article
                className="card signal-card"
                aria-labelledby={`signal-${signal.id}`}
              >
                <div className="signal-rank" title={t.tower.rankHint}>
                  <span>{t.tower.rank}</span>
                  <strong>
                    {signal.rank == null ? "—" : `#${signal.rank}`}
                  </strong>
                  {signal.rank == null ? <span>{t.tower.unranked}</span> : null}
                </div>
                <div className="min-w-0 space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="eyebrow">{signal.typeLabel}</p>
                      <h3
                        id={`signal-${signal.id}`}
                        className="text-lg font-semibold"
                      >
                        {signal.headline}
                      </h3>
                    </div>
                    <SeverityBadge value={signal.severity} />
                  </div>
                  <SubjectLinks signal={signal} />
                  <p>{signal.reason}</p>
                  <Facts
                    items={[
                      { label: t.tower.forecast, value: signal.forecast },
                      { label: t.tower.interval, value: signal.interval },
                      { label: t.tower.materiality, value: signal.materiality },
                    ]}
                  />
                  <div className="flex flex-wrap items-center gap-3">
                    <SupportBadge value={signal.support} />
                    <span className="text-sm text-muted">
                      {t.tower.fallback}: {signal.fallback}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Link
                      className="btn btn-primary"
                      to={`/signals/${encodeURIComponent(signal.id)}`}
                    >
                      {t.tower.investigate}
                    </Link>
                    <button
                      className="btn"
                      onClick={() => setExplaining(signal)}
                    >
                      {t.tower.explain}
                    </button>
                  </div>
                </div>
              </article>
            </li>
          ))}
        </ol>
      )}
      {explaining ? (
        <ExplanationDrawer
          signalId={explaining.id}
          identity={explaining.identity}
          onClose={() => setExplaining(null)}
        />
      ) : null}
    </>
  );
}
