import { Link, useNavigate } from "react-router-dom";

import { useOverview } from "../api/queries";
import type { AreaKpis } from "../api/types";
import { type Column, DataTable } from "../components/DataTable";
import { Kpi, KpiGrid } from "../components/Kpi";
import { PageHeader, Section } from "../components/PageHeader";
import { QueryState } from "../components/QueryState";
import { KpiSkeleton, TableSkeleton } from "../components/Skeleton";
import { t } from "../i18n";
import { fmtDate, fmtDays, fmtIndex, fmtInt, fmtPercent } from "../lib/format";

const columns: Column<AreaKpis>[] = [
  {
    key: "name",
    header: t.overview.columns.region,
    render: (r) => (
      <Link to={`/regions/${r.code}`} className="link font-medium">
        {r.name}
      </Link>
    ),
    sortValue: (r) => r.name,
  },
  {
    key: "load_index_max",
    header: t.overview.columns.loadIndexMax,
    align: "right",
    render: (r) => fmtIndex(r.load_index_max),
    sortValue: (r) => r.load_index_max,
  },
  {
    key: "queue_now",
    header: t.overview.columns.queue,
    align: "right",
    render: (r) => fmtInt(r.queue_now),
    sortValue: (r) => r.queue_now,
  },
  {
    key: "refusal_rate_28d",
    header: t.overview.columns.refusalRate,
    align: "right",
    render: (r) => fmtPercent(r.refusal_rate_28d),
    sortValue: (r) => r.refusal_rate_28d,
  },
  {
    key: "median_wait_28d",
    header: t.overview.columns.medianWait,
    align: "right",
    render: (r) => fmtDays(r.median_wait_28d),
    sortValue: (r) => r.median_wait_28d,
  },
  {
    key: "n_hospitals_high_load",
    header: t.overview.columns.highLoad,
    align: "right",
    render: (r) =>
      `${fmtInt(r.n_hospitals_high_load)} / ${fmtInt(r.n_hospitals)}`,
    sortValue: (r) => r.n_hospitals_high_load,
  },
];

export function OverviewPage() {
  const overview = useOverview();
  const navigate = useNavigate();

  return (
    <>
      <PageHeader title={t.overview.title} />
      <QueryState
        query={overview}
        skeleton={
          <div className="space-y-6">
            <KpiSkeleton />
            <TableSkeleton rows={10} />
          </div>
        }
      >
        {(data) => (
          <>
            <section className="space-y-2" aria-label={t.overview.title}>
              <KpiGrid>
                <Kpi
                  label={t.metrics.queueNow}
                  value={fmtInt(data.national.queue_now)}
                  hint={t.metrics.queueNowHint}
                />
                <Kpi
                  label={t.metrics.medianWait}
                  value={fmtDays(data.national.median_wait_28d)}
                  hint={t.metrics.medianWaitHint}
                />
                <Kpi
                  label={t.metrics.refusalRate}
                  value={fmtPercent(data.national.refusal_rate_28d)}
                  hint={t.metrics.refusalRateHint}
                />
                <Kpi
                  label={t.metrics.hospitalsHighLoad}
                  value={fmtInt(data.national.n_hospitals_high_load)}
                  sub={t.common.hospitals(data.national.n_hospitals)}
                  hint={t.metrics.hospitalsHighLoadHint}
                />
              </KpiGrid>
              <p className="text-sm text-muted">
                {t.common.source(fmtDate(data.as_of_date))}
              </p>
            </section>

            <Section
              title={t.overview.regionsTitle}
              caption={t.overview.regionsCaption}
              id="regions"
            >
              <DataTable
                columns={columns}
                rows={data.regions}
                rowKey={(r) => r.code}
                caption={t.overview.regionsTitle}
                initialSort={{ key: "load_index_max", direction: "desc" }}
                onRowClick={(r) => navigate(`/regions/${r.code}`)}
              />
            </Section>
          </>
        )}
      </QueryState>
    </>
  );
}
