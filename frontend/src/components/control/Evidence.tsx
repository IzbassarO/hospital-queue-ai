import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../api/client";
import {
  label,
  type CountsView,
  type Fact,
  type Severity,
  type SnapshotView,
  type Support,
} from "../../api/operational-adapters";
import { t } from "../../i18n";
import { fmtDate } from "../../lib/format";
import { Kpi, KpiGrid } from "../Kpi";
import { TableSkeleton } from "../Skeleton";

export function EvidenceState<T>({
  query,
  children,
}: {
  query: UseQueryResult<T, Error>;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <TableSkeleton rows={4} columns={3} />;
  if (query.isError) {
    const error = query.error;
    const status = error instanceof ApiError ? error.status : undefined;
    return (
      <div className="card state-panel" role="alert">
        <h2 className="font-semibold">
          {status === 404 ? t.tower.noPublication : t.tower.unavailable}
        </h2>
        <p>
          {status === 404
            ? t.tower.noPublicationHint
            : status === 409
              ? t.tower.publicationChanged
              : error instanceof ApiError && error.kind === "shape"
                ? t.tower.shapeError
                : status === 401
                  ? t.errors.auth
                  : status === 403
                    ? t.errors.forbidden
                    : t.tower.unavailableHint}
        </p>
        <button className="btn" onClick={() => void query.refetch()}>
          {t.common.retry}
        </button>
      </div>
    );
  }
  return <>{children(query.data)}</>;
}
export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="card state-panel text-muted" role="status">
      {children}
    </p>
  );
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <p className="notice" role="status">
      {children}
    </p>
  );
}
export function Facts({ items }: { items: Fact[] }) {
  return (
    <dl className="facts">
      {items.map((item, i) => (
        <div key={`${item.label}-${i}`}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
export function Lines({ items }: { items: string[] }) {
  return (
    <ul className="evidence-lines list-disc space-y-1 pl-5">
      {items.map((line, i) => (
        <li key={i}>{line}</li>
      ))}
    </ul>
  );
}
export function Limitations({ items }: { items: string[] }) {
  return (
    <section className="limitations">
      <h3 className="font-semibold">{t.tower.limitations}</h3>
      {items.length ? <Lines items={items} /> : <p>{t.tower.noLimitations}</p>}
    </section>
  );
}
export function Provenance({ items }: { items: Fact[] }) {
  return (
    <details className="provenance">
      <summary>{t.tower.provenance}</summary>
      <Facts items={items} />
      <Link className="link mt-3 inline-block" to="/assurance">
        {t.tower.assurance}
      </Link>
    </details>
  );
}
export function SeverityBadge({ value }: { value: Severity }) {
  return (
    <span
      className={`evidence-badge severity-${value.toLowerCase()}`}
      aria-label={`${t.tower.severity}: ${label(value)}`}
    >
      {label(value)}
    </span>
  );
}
export function SupportBadge({ value }: { value: Support }) {
  return (
    <span
      className={`evidence-badge support-${value.toLowerCase()}`}
      aria-label={`${t.tower.support}: ${label(value)}`}
    >
      {label(value)}
    </span>
  );
}
export function Publication({ snapshot }: { snapshot: SnapshotView }) {
  return (
    <section className="publication space-y-3" aria-label={t.tower.published}>
      <div className="flex flex-wrap justify-between gap-3 text-sm">
        <p>
          <strong>
            {t.tower.origin}: {fmtDate(snapshot.origin)}
          </strong>{" "}
          · {t.tower.published}: {snapshot.published}
        </p>
        <span>
          {label(snapshot.status)} · {t.tower.freshness}:{" "}
          {label(snapshot.freshness)}
        </span>
      </div>
      {snapshot.status === "EMPTY" ? (
        <Notice>{t.tower.emptyPublication}</Notice>
      ) : null}
      {snapshot.status === "DEGRADED" || snapshot.freshness === "DEGRADED" ? (
        <Notice>{t.tower.degraded}</Notice>
      ) : null}
      {snapshot.freshness === "UNKNOWN" ? (
        <Notice>{t.tower.unknownFreshness}</Notice>
      ) : snapshot.freshness === "STALE" ? (
        <Notice>{t.tower.stale}</Notice>
      ) : null}
      {snapshot.limitations.length ? (
        <Limitations items={snapshot.limitations} />
      ) : null}
      <Provenance
        items={[
          { label: "Publication", value: snapshot.id },
          ...snapshot.facts,
        ]}
      />
    </section>
  );
}
export function Summary({ counts }: { counts: CountsView }) {
  return (
    <div className="space-y-4">
      <KpiGrid>
        <Kpi
          label={t.tower.total}
          value={counts.total}
          hint={t.tower.totalHint}
        />
        <Kpi label={t.tower.high} value={counts.high} />
        <Kpi
          label={t.tower.direct}
          value={counts.direct}
          hint={t.tower.supportHint}
        />
        <Kpi label={t.tower.calibrated} value={counts.calibrated} />
      </KpiGrid>
      <div className="grid gap-4 lg:grid-cols-2">
        {[
          { title: t.tower.severityMix, items: counts.severity },
          { title: t.tower.supportMix, items: counts.support },
        ].map((group) => (
          <section className="card p-4" key={group.title}>
            <h2 className="mb-3 font-semibold">{group.title}</h2>
            <dl className="flex flex-wrap gap-x-6 gap-y-2">
              {group.items.map((item) => (
                <div key={item.label}>
                  <dt className="text-sm text-muted">{item.label}</dt>
                  <dd className="font-semibold tabular-nums">{item.value}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </div>
  );
}
