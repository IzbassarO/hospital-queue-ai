import type { ReactNode } from "react";

import { InfoTip } from "./InfoTip";

export function Kpi({
  label,
  value,
  hint,
  sub,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  sub?: ReactNode;
}) {
  return (
    <div className="card flex min-w-0 flex-col gap-1 px-4 py-3">
      <dt className="flex items-center gap-1 text-sm font-medium text-muted">
        <span>{label}</span>
        {hint ? (
          <InfoTip label={label} width="w-72">
            {hint}
          </InfoTip>
        ) : null}
      </dt>
      <dd className="text-2xl font-semibold tabular-nums text-ink">{value}</dd>
      {sub ? <dd className="text-sm text-muted">{sub}</dd> : null}
    </div>
  );
}

export function KpiGrid({
  children,
  columns = 4,
}: {
  children: ReactNode;
  columns?: 4 | 6;
}) {
  return (
    <dl
      className={`grid gap-3 ${columns === 6 ? "grid-cols-3 xl:grid-cols-6" : "grid-cols-2 lg:grid-cols-4"}`}
    >
      {children}
    </dl>
  );
}
