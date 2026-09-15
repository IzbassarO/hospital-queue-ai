import { Link, useSearchParams } from "react-router-dom";

import { PAGE_SIZE, useAlerts, useDictionaries } from "../api/queries";
import type { Alert } from "../api/types";
import { ErrorState } from "../components/ErrorState";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { TableSkeleton } from "../components/Skeleton";
import { StatusBadge } from "../components/StatusBadge";
import { t } from "../i18n";
import { fmtDays, fmtIndex, fmtInt, fmtPercent, fmtTrend } from "../lib/format";
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

export function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const region = params.get("region") || undefined;
  const offset = Number(params.get("offset") ?? 0) || 0;
  const dictionaries = useDictionaries();
  const alerts = useAlerts(region, offset);

  return (
    <>
      <PageHeader
        title={t.alerts.title}
        aside={
          <div className="w-80">
            <label
              htmlFor="alert-region"
              className="mb-1 block text-sm font-medium"
            >
              {t.alerts.regionFilter}
            </label>
            <select
              id="alert-region"
              className="field"
              value={region ?? ""}
              disabled={!dictionaries.data}
              onChange={(e) =>
                setParams(e.target.value ? { region: e.target.value } : {})
              }
            >
              <option value="">{t.alerts.allRegions}</option>
              {dictionaries.data?.regions.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.name}
                </option>
              ))}
            </select>
          </div>
        }
      >
        <p className="max-w-4xl text-muted">{t.alerts.caption}</p>
      </PageHeader>

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
            onChange={(next) =>
              setParams({ ...(region ? { region } : {}), offset: String(next) })
            }
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
              setParams({
                ...(region ? { region } : {}),
                offset: String(next),
              });
              window.scrollTo({ top: 0 });
            }}
          />
        </div>
      )}
    </>
  );
}
