import { Link, useSearchParams } from "react-router-dom";

import {
  PAGE_SIZE,
  useAlerts,
  useConfig,
  useDictionaries,
} from "../api/queries";
import type { Alert, Status } from "../api/types";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { TableSkeleton } from "../components/Skeleton";
import { StatusBadge } from "../components/StatusBadge";
import { t } from "../i18n";
import {
  fmtDays,
  fmtIndex,
  fmtInt,
  fmtNumber,
  fmtPercent,
  fmtTrend,
} from "../lib/format";
import { hospitalPath, regionPath } from "../lib/paths";

function AlertCard({ alert }: { alert: Alert }) {
  return (
    <article className="card grid grid-cols-[1fr_auto] gap-x-6 gap-y-2 p-4">
      <div className="min-w-0 space-y-1">
        <h2 className="text-lg font-semibold leading-snug">
          <Link
            to={hospitalPath(alert.org_code, alert.profile_code)}
            className="link"
          >
            {alert.org_name}
          </Link>
        </h2>
        <p className="text-muted">
          <Link to={regionPath(alert.region_code)} className="hover:underline">
            {alert.region_name}
          </Link>{" "}
          · {alert.profile_name} ({alert.profile_code})
          {alert.region_rank !== null
            ? ` · ${t.metrics.rank(alert.region_rank, alert.region_n_ranked)}`
            : ""}
        </p>
      </div>
      <div className="flex items-start gap-3">
        <StatusBadge status={alert.status} />
        <p className="text-right">
          <span className="block text-sm text-muted">
            {t.metrics.loadIndex}
          </span>
          <span className="text-2xl font-semibold tabular-nums">
            {fmtIndex(alert.load_index)}
          </span>
        </p>
      </div>
      <ul className="col-span-2 list-disc space-y-1 pl-5">
        {alert.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
      <dl className="col-span-2 flex flex-wrap gap-x-8 gap-y-1 text-sm">
        <div className="flex gap-1.5">
          <dt className="text-muted">{t.metrics.queueNow}:</dt>
          <dd className="font-medium tabular-nums">
            {fmtInt(alert.queue_now)}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-muted">{t.metrics.backlog}:</dt>
          <dd className="font-medium tabular-nums">
            {fmtDays(alert.backlog_days)}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-muted">{t.metrics.refusalRate}:</dt>
          <dd className="font-medium tabular-nums">
            {fmtPercent(alert.refusal_rate_28d)}
          </dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-muted">{t.metrics.excessTrend}:</dt>
          <dd className="font-medium tabular-nums">
            {fmtTrend(alert.queue_trend_4w)}
          </dd>
        </div>
      </dl>
    </article>
  );
}

const STATUSES: Status[] = ["high", "elevated", "normal", "insufficient_data"];
const FILTERS = ["region", "profile", "status"] as const;

export function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const filters = {
    region: params.get("region") || undefined,
    profile: params.get("profile") || undefined,
    status: params.get("status") || undefined,
  };
  const offset = Number(params.get("offset") ?? 0) || 0;
  const dictionaries = useDictionaries();
  const config = useConfig();
  const alerts = useAlerts(filters, offset);

  /** new filter values reset paging */
  const setFilter = (name: (typeof FILTERS)[number], value: string) => {
    const next = new URLSearchParams();
    for (const key of FILTERS) {
      const current = key === name ? value : (filters[key] ?? "");
      if (current) next.set(key, current);
    }
    setParams(next);
  };
  const pageParams = (next: number) => {
    const out = new URLSearchParams();
    for (const key of FILTERS) if (filters[key]) out.set(key, filters[key]);
    out.set("offset", String(next));
    return out;
  };
  const rule = config.data?.alerts;

  return (
    <>
      <PageHeader title={t.alerts.title}>
        {rule ? (
          <p className="max-w-4xl text-muted">
            {t.alerts.caption(
              fmtNumber(rule.load_index_min, 0),
              fmtNumber(rule.queue_trend_min_pct, 0),
              rule.queue_trend_min_queue_now,
            )}
          </p>
        ) : null}
      </PageHeader>

      <div
        className="flex flex-wrap items-end gap-4"
        role="group"
        aria-label={t.alerts.title}
      >
        <div className="w-72">
          <label
            htmlFor="alert-region"
            className="mb-1 block text-sm font-medium"
          >
            {t.alerts.regionFilter}
          </label>
          <select
            id="alert-region"
            className="field"
            value={filters.region ?? ""}
            disabled={!dictionaries.data}
            onChange={(e) => setFilter("region", e.target.value)}
          >
            <option value="">{t.alerts.allRegions}</option>
            {dictionaries.data?.regions.map((r) => (
              <option key={r.code} value={r.code}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        <div className="w-96">
          <label
            htmlFor="alert-profile"
            className="mb-1 block text-sm font-medium"
          >
            {t.alerts.profileFilter}
          </label>
          <select
            id="alert-profile"
            className="field"
            value={filters.profile ?? ""}
            disabled={!dictionaries.data}
            onChange={(e) => setFilter("profile", e.target.value)}
          >
            <option value="">{t.alerts.allProfiles}</option>
            {dictionaries.data?.profiles.map((p) => (
              <option key={p.code} value={p.code}>
                {p.name} ({p.code})
              </option>
            ))}
          </select>
        </div>
        <div className="w-60">
          <label
            htmlFor="alert-status"
            className="mb-1 block text-sm font-medium"
          >
            {t.alerts.statusFilter}
          </label>
          <select
            id="alert-status"
            className="field"
            value={filters.status ?? ""}
            onChange={(e) => setFilter("status", e.target.value)}
          >
            <option value="">{t.alerts.allStatuses}</option>
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {t.statusLong[status]}
              </option>
            ))}
          </select>
        </div>
      </div>

      {alerts.isPending ? (
        <TableSkeleton rows={6} columns={4} />
      ) : alerts.isError ? (
        <ErrorState
          error={alerts.error}
          onRetry={() => void alerts.refetch()}
        />
      ) : (
        <div
          className={`space-y-3 ${alerts.isPlaceholderData ? "opacity-60" : ""}`}
        >
          <Pagination
            total={alerts.data.total}
            limit={PAGE_SIZE}
            offset={offset}
            busy={alerts.isFetching}
            onChange={(next) => setParams(pageParams(next))}
          />
          {alerts.data.items.length === 0 ? (
            <p className="card p-6 text-center text-muted">{t.alerts.empty}</p>
          ) : (
            <ol className="space-y-3">
              {alerts.data.items.map((alert) => (
                <li key={`${alert.org_code}-${alert.profile_code}`}>
                  <AlertCard alert={alert} />
                </li>
              ))}
            </ol>
          )}
          <Pagination
            total={alerts.data.total}
            limit={PAGE_SIZE}
            offset={offset}
            busy={alerts.isFetching}
            onChange={(next) => {
              setParams(pageParams(next));
              window.scrollTo({ top: 0 });
            }}
          />
        </div>
      )}
    </>
  );
}
