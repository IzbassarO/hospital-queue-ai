import type { HospitalProfileStatus } from "../../api/types";
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
  fmtPercent,
} from "../../lib/format";
import { regionPath } from "../../lib/paths";

export function CardHeader({ status }: { status: HospitalProfileStatus }) {
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
                  {t.loadIndex.formula.map((line) => (
                    <span key={line} className="mb-1 block">
                      {line}
                    </span>
                  ))}
                </InfoTip>
              </p>
              <p className="text-4xl font-semibold tabular-nums leading-none">
                {fmtIndex(status.load_index)}
              </p>
              <StatusBadge status={status.status} size="lg" />
            </div>
            <LoadIndexBars components={status.components} />
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
