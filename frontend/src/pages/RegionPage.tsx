import { useMemo } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

import {
  PAGE_SIZE,
  useDictionaries,
  useConfig,
  useOverview,
  useRegion,
  useRegionHospitals,
} from "../api/queries";
import type { HospitalProfileStatus, RegionDetail } from "../api/types";
import { type Column, DataTable } from "../components/DataTable";
import { ErrorState } from "../components/ErrorState";
import { Kpi, KpiGrid } from "../components/Kpi";
import { PageHeader, Section } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { KpiSkeleton, Skeleton, TableSkeleton } from "../components/Skeleton";
import { StatusBadge } from "../components/StatusBadge";
import { t } from "../i18n";
import {
  fmtDate,
  fmtDays,
  fmtIndex,
  fmtInt,
  fmtNumber,
  fmtPercent,
  fmtTrend,
} from "../lib/format";
import { hospitalPath } from "../lib/paths";

function hospitalColumns(trendHint: string): Column<HospitalProfileStatus>[] {
  return [
    {
      key: "org_name",
      header: t.metrics.hospital,
      render: (h) => (
        <Link
          to={hospitalPath(h.org_code, h.profile_code)}
          className="link font-medium"
        >
          {h.org_name}
        </Link>
      ),
    },
    {
      key: "status",
      header: t.metrics.status,
      render: (h) => <StatusBadge status={h.status} />,
    },
    {
      key: "load_index",
      header: t.metrics.loadIndex,
      align: "right",
      render: (h) => fmtIndex(h.load_index),
    },
    {
      key: "queue_now",
      header: t.metrics.queueNow,
      align: "right",
      render: (h) => fmtInt(h.queue_now),
    },
    {
      key: "backlog_days",
      header: t.metrics.backlogShort,
      align: "right",
      render: (h) => fmtDays(h.backlog_days),
    },
    {
      key: "median_wait_28d",
      header: t.metrics.medianWait,
      align: "right",
      render: (h) => fmtDays(h.median_wait_28d),
    },
    {
      key: "refusal_rate_28d",
      header: t.metrics.refusalRate,
      align: "right",
      render: (h) => fmtPercent(h.refusal_rate_28d),
    },
    {
      key: "forecast_registrations_14d",
      header: t.metrics.forecast14Short,
      align: "right",
      render: (h) => fmtInt(h.forecast_registrations_14d),
    },
    {
      key: "queue_trend_4w",
      header: <abbr title={trendHint}>{t.metrics.excessTrendShort}</abbr>,
      headerText: t.metrics.excessTrend,
      align: "right",
      render: (h) => fmtTrend(h.queue_trend_4w),
    },
  ];
}

export function RegionPage() {
  const { code = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const region = useRegion(code);
  const dictionaries = useDictionaries();
  const overview = useOverview();
  const config = useConfig();

  const profiles = useMemo(
    () => profileOptions(region.data, dictionaries.data?.profiles),
    [region.data, dictionaries.data],
  );
  const requested = params.get("profile");
  const selected = profiles.find((p) => p.code === requested) ?? profiles[0];
  const offset = Number(params.get("offset") ?? 0) || 0;
  const hospitals = useRegionHospitals(code, selected?.code, offset);

  const median = config.data?.queue_trend_national_median_4w;
  const trendHint = t.metrics.excessTrendHint(
    median == null
      ? t.common.noData
      : `${fmtNumber(median, 1)} ${t.units.percentPerWeek}`,
  );
  const columns = useMemo(() => hospitalColumns(trendHint), [trendHint]);

  if (region.isError) {
    return (
      <>
        <PageHeader
          title={t.metrics.region}
          crumbs={[{ label: t.nav.overview, to: "/" }, { label: code }]}
        />
        <ErrorState
          error={region.error}
          onRetry={() => void region.refetch()}
        />
      </>
    );
  }

  const data = region.data;
  const selectedStatus = data?.profiles.find(
    (p) => p.profile_code === selected?.code,
  );

  return (
    <>
      <PageHeader
        title={data ? data.region.name : <Skeleton className="h-8 w-72" />}
        crumbs={[
          { label: t.nav.overview, to: "/" },
          { label: data?.region.name ?? code },
        ]}
      >
        {overview.data ? (
          <p className="text-sm text-muted">
            {t.common.asOf(fmtDate(overview.data.as_of_date))}
          </p>
        ) : null}
      </PageHeader>

      {data ? (
        <section aria-label={t.region.kpisTitle}>
          <KpiGrid>
            <Kpi
              label={t.metrics.queueNow}
              value={fmtInt(data.region.queue_now)}
              hint={t.metrics.queueNowHint}
            />
            <Kpi
              label={t.metrics.medianWait}
              value={fmtDays(data.region.median_wait_28d)}
              hint={t.metrics.medianWaitHint}
            />
            <Kpi
              label={t.metrics.refusalRate}
              value={fmtPercent(data.region.refusal_rate_28d)}
              hint={t.metrics.refusalRateHint}
            />
            <Kpi
              label={t.metrics.hospitalsHighLoad}
              value={fmtInt(data.region.n_hospitals_high_load)}
              sub={t.common.hospitals(data.region.n_hospitals)}
              hint={t.metrics.hospitalsHighLoadHint}
            />
          </KpiGrid>
        </section>
      ) : (
        <KpiSkeleton />
      )}

      {data && profiles.length === 0 ? (
        <p className="text-muted">{t.region.noProfiles}</p>
      ) : null}

      {data && selected ? (
        <Section
          title={t.region.hospitalsTitle(selected.name)}
          caption={t.region.hospitalsCaption}
          id="hospitals"
          actions={
            <div className="w-[26rem]">
              <label
                htmlFor="profile"
                className="mb-1 block text-sm font-medium text-ink"
              >
                {t.region.profileLabel}
              </label>
              <select
                id="profile"
                className="field"
                value={selected.code}
                onChange={(e) =>
                  setParams({ profile: e.target.value }, { replace: false })
                }
              >
                {profiles.map((p) => (
                  <option key={p.code} value={p.code}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
          }
        >
          {selectedStatus ? (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <StatusBadge status={selectedStatus.status} />
              <span>
                {t.metrics.loadIndex}:{" "}
                <strong className="tabular-nums">
                  {fmtIndex(selectedStatus.load_index)}
                </strong>
              </span>
              <span className="text-muted">
                {t.region.profileSummary(
                  selectedStatus.n_hospitals,
                  selectedStatus.n_hospitals_high_load,
                )}
              </span>
            </div>
          ) : null}
          {hospitals.isError ? (
            <ErrorState
              error={hospitals.error}
              onRetry={() => void hospitals.refetch()}
            />
          ) : hospitals.data ? (
            <div
              className={`space-y-3 ${hospitals.isPlaceholderData ? "opacity-60" : ""}`}
            >
              <DataTable
                columns={columns}
                rows={hospitals.data.items}
                rowKey={(h) => `${h.org_code}-${h.profile_code}`}
                caption={t.region.hospitalsTitle(selected.name)}
                onRowClick={(h) =>
                  navigate(hospitalPath(h.org_code, h.profile_code))
                }
                empty={t.region.noHospitals}
              />
              <Pagination
                total={hospitals.data.total}
                limit={PAGE_SIZE}
                offset={offset}
                busy={hospitals.isFetching}
                onChange={(next) =>
                  setParams({ profile: selected.code, offset: String(next) })
                }
              />
            </div>
          ) : (
            <TableSkeleton rows={6} columns={9} />
          )}
        </Section>
      ) : !data ? (
        <TableSkeleton rows={6} columns={9} />
      ) : null}
    </>
  );
}

type ProfileOption = { code: string; name: string; label: string };

/** Profiles present in the region (highest regional load first), named from the dictionary. */
function profileOptions(
  region: RegionDetail | undefined,
  dictionary:
    { code: string; name: string; is_day_hospital: boolean }[] | undefined,
): ProfileOption[] {
  if (!region) return [];
  const byCode = new Map((dictionary ?? []).map((p) => [p.code, p]));
  return region.profiles.map((p) => {
    const entry = byCode.get(p.profile_code);
    const name = entry?.name ?? p.profile_name;
    const suffix = entry?.is_day_hospital ? ` (${t.region.dayHospital})` : "";
    const index =
      p.load_index === null
        ? t.status.insufficient_data.toLowerCase()
        : `${t.metrics.loadIndex.toLowerCase()} ${fmtIndex(p.load_index)}`;
    return { code: p.profile_code, name, label: `${name}${suffix} — ${index}` };
  });
}
