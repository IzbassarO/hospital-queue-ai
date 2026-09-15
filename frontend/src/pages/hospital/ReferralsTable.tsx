import { useState } from "react";

import { REFERRALS_PAGE_SIZE, useReferrals } from "../../api/queries";
import type { Referral, ReferralFactor } from "../../api/types";
import { type Column, DataTable } from "../../components/DataTable";
import { Direction } from "../../components/Direction";
import { ErrorState } from "../../components/ErrorState";
import {
  IconAlertTriangle,
  IconChevronDown,
  IconChevronRight,
} from "../../components/icons";
import { Section } from "../../components/PageHeader";
import { Pagination } from "../../components/Pagination";
import { TableSkeleton } from "../../components/Skeleton";
import { t } from "../../i18n";
import { featureLabel } from "../../lib/features";
import { fmtDate, fmtDays, fmtPercent, fmtSigned } from "../../lib/format";

type Sort = "risk" | "wait";

function FactorRows({
  title,
  factors,
  unit,
}: {
  title: string;
  factors: ReferralFactor[];
  unit: "days" | "pp";
}) {
  return (
    <div>
      <h4 className="mb-1 font-semibold">{title}</h4>
      <ol className="space-y-1.5">
        {factors.map((f) => (
          <li key={f.feature} className="flex items-start gap-2 text-[15px]">
            <Direction direction={f.direction} />
            <span className="min-w-0 flex-1">
              <span className="font-medium">
                {featureLabel(f.feature, f.feature)}
              </span>
              : <span className="break-words">{f.value_display}</span>
            </span>
            <span className="num font-semibold">
              {unit === "days"
                ? fmtSigned(f.effect, 1, ` ${t.units.days}`)
                : fmtSigned(f.effect * 100, 1, ` ${t.units.pp}`)}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function ReferralsTable({
  org,
  profile,
}: {
  org: string;
  profile: string;
}) {
  const [sort, setSort] = useState<Sort>("risk");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const query = useReferrals(org, profile, sort, offset);

  const columns: Column<Referral>[] = [
    {
      key: "toggle",
      header: <span className="sr-only">{t.referrals.columns.details}</span>,
      headerText: t.referrals.columns.details,
      width: "w-10",
      render: (r) => {
        const open = expanded === r.hospitalization_code;
        return (
          <button
            type="button"
            className="rounded p-1 text-accent-700 hover:bg-accent-100"
            aria-expanded={open}
            aria-label={open ? t.referrals.collapse : t.referrals.expand}
            onClick={() => setExpanded(open ? null : r.hospitalization_code)}
          >
            {open ? (
              <IconChevronDown size={18} />
            ) : (
              <IconChevronRight size={18} />
            )}
          </button>
        );
      },
    },
    {
      key: "date",
      header: t.referrals.columns.date,
      render: (r) => (
        <span className="tabular-nums">{fmtDate(r.registration_date)}</span>
      ),
    },
    {
      key: "icd",
      header: t.referrals.columns.diagnosis,
      render: (r) => r.icd10_code ?? t.common.noData,
    },
    {
      key: "purpose",
      header: t.referrals.columns.purpose,
      render: (r) => r.referral_purpose ?? t.common.noData,
    },
    {
      key: "wait",
      header: t.referrals.columns.predWait,
      align: "right",
      render: (r) => fmtDays(r.pred_wait_days),
    },
    {
      key: "risk",
      header: t.referrals.columns.refusalProb,
      align: "right",
      render: (r) => (
        <span className="inline-flex items-center justify-end gap-1.5">
          {r.is_high_risk ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-high-bg px-1.5 text-xs font-semibold text-high-fg">
              <IconAlertTriangle size={12} />
              {t.referrals.highRisk}
            </span>
          ) : null}
          {fmtPercent(r.pred_refusal_prob)}
        </span>
      ),
    },
  ];

  return (
    <Section
      title={t.referrals.title}
      caption={t.referrals.caption}
      id="referrals"
      actions={
        <div className="flex items-center gap-2">
          <label htmlFor="referral-sort" className="text-sm font-medium">
            {t.referrals.sortLabel}
          </label>
          <select
            id="referral-sort"
            className="field w-56"
            value={sort}
            onChange={(e) => {
              setSort(e.target.value as Sort);
              setOffset(0);
              setExpanded(null);
            }}
          >
            <option value="risk">{t.referrals.sortRisk}</option>
            <option value="wait">{t.referrals.sortWait}</option>
          </select>
        </div>
      }
    >
      {query.isPending ? (
        <TableSkeleton rows={8} columns={6} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div
          className={`space-y-3 ${query.isPlaceholderData ? "opacity-60" : ""}`}
        >
          <DataTable
            columns={columns}
            rows={query.data.items}
            rowKey={(r) => r.hospitalization_code}
            caption={t.referrals.title}
            empty={t.referrals.empty}
            onRowClick={(r) =>
              setExpanded((cur) =>
                cur === r.hospitalization_code ? null : r.hospitalization_code,
              )
            }
            expandedRow={(r) =>
              expanded === r.hospitalization_code ? (
                <div className="grid gap-6 lg:grid-cols-2">
                  <FactorRows
                    title={t.referrals.explanationWait}
                    factors={r.explanation.wait_time ?? []}
                    unit="days"
                  />
                  <FactorRows
                    title={t.referrals.explanationRisk}
                    factors={r.explanation.refusal_risk ?? []}
                    unit="pp"
                  />
                </div>
              ) : null
            }
            maxHeight="max-h-[80vh]"
          />
          <Pagination
            total={query.data.total}
            limit={REFERRALS_PAGE_SIZE}
            offset={offset}
            busy={query.isFetching}
            onChange={(next) => {
              setOffset(next);
              setExpanded(null);
            }}
          />
        </div>
      )}
    </Section>
  );
}
