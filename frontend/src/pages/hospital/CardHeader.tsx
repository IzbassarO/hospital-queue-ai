import { useConfig } from "../../api/queries";
import type { Config, HospitalProfileStatus } from "../../api/types";
import { InfoTip } from "../../components/InfoTip";
import { Kpi, KpiGrid } from "../../components/Kpi";
import { LoadIndexBars } from "../../components/LoadIndexBars";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import { t } from "../../i18n";
import {
  fmtDate,
  fmtDays,
  fmtIndex,
  fmtInt,
  fmtNumber,
  fmtPercent,
} from "../../lib/format";
import { regionPath } from "../../lib/paths";
import { ExportButtons } from "./ExportButtons";

function formulaLines(config: Config): string[] {
  const { load_index: li, status_thresholds: st } = config;
  return t.loadIndex.formula({
    backlog: fmtNumber(li.weights.backlog_rank, 2),
    refusal: fmtNumber(li.weights.refusal_rate, 2),
    trend: fmtNumber(li.weights.queue_trend, 2),
    refusalCap: fmtPercent(li.refusal_rate_cap, 0),
    trendCap: fmtNumber(li.queue_trend_cap_pct, 0),
    minRegistrations: config.min_registrations_28d,
    high: fmtNumber(st.high, 0),
    elevated: fmtNumber(st.elevated, 0),
  });
}

export function CardHeader({ status }: { status: HospitalProfileStatus }) {
  const config = useConfig();
  return (
    <>
      <PageHeader
        crumbs={[
          { label: t.nav.overview, to: "/" },
          { label: status.region_name, to: regionPath(status.region_code) },
          {
            label: status.profile_name,
            to: regionPath(status.region_code, status.profile_code),
          },
          { label: status.org_code },
        ]}
        title={status.org_name}
        aside={
          <div className="card flex items-start gap-5 px-4 py-3">
            <div className="space-y-2">
              <p className="flex items-center gap-1 text-sm font-medium text-muted">
                {t.metrics.loadIndex}
                <InfoTip
                  label={t.loadIndex.formulaTitle}
                  align="right"
                  width="w-[28rem]"
                >
                  <strong className="mb-1 block">
                    {t.loadIndex.formulaTitle}
                  </strong>
                  {config.data
                    ? formulaLines(config.data).map((line) => (
                        <span key={line} className="mb-1 block">
                          {line}
                        </span>
                      ))
                    : t.common.loading}
                </InfoTip>
              </p>
              <p className="text-4xl font-semibold tabular-nums leading-none">
                {fmtIndex(status.load_index)}
              </p>
              <StatusBadge status={status.status} size="lg" />
            </div>
            <LoadIndexBars
              components={status.components}
              weights={config.data?.load_index.weights}
            />
          </div>
        }
      >
        <p className="text-lg text-ink">
          {status.region_name} · {t.metrics.profile.toLowerCase()} «
          {status.profile_name}» ({status.profile_code})
        </p>
        <p className="text-sm text-muted">
          {status.region_rank !== null
            ? `${t.metrics.rank(status.region_rank, status.region_n_ranked)} · `
            : ""}
          {t.common.asOf(fmtDate(status.as_of_date))}
        </p>
        <div className="pt-2">
          <ExportButtons org={status.org_code} profile={status.profile_code} />
        </div>
      </PageHeader>

      <section aria-label={t.hospital.kpisTitle}>
        <KpiGrid columns={6}>
          <Kpi
            label={t.metrics.queueNow}
            value={fmtInt(status.queue_now)}
            hint={t.metrics.queueNowHint}
          />
          <Kpi
            label={t.metrics.backlog}
            value={fmtDays(status.backlog_days)}
            hint={t.metrics.backlogHint}
          />
          <Kpi
            label={t.metrics.medianWait}
            value={fmtDays(status.median_wait_28d)}
            hint={t.metrics.medianWaitHint}
          />
          <Kpi
            label={t.metrics.refusalRate}
            value={fmtPercent(status.refusal_rate_28d)}
            hint={t.metrics.refusalRateHint}
          />
          <Kpi
            label={t.metrics.registrations28}
            value={fmtInt(status.registrations_28d)}
          />
          <Kpi
            label={t.metrics.forecast14}
            value={fmtInt(status.forecast_registrations_14d)}
          />
        </KpiGrid>
      </section>
    </>
  );
}
