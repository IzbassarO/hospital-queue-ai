import { t } from "../i18n";

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function KpiSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div
      className={`grid gap-3 ${count > 4 ? "grid-cols-3 xl:grid-cols-6" : "grid-cols-2 lg:grid-cols-4"}`}
    >
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card space-y-2 px-4 py-3">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-7 w-1/2" />
        </div>
      ))}
    </div>
  );
}

export function TableSkeleton({
  rows = 8,
  columns = 6,
}: {
  rows?: number;
  columns?: number;
}) {
  return (
    <div className="card p-4" role="status" aria-live="polite">
      <span className="sr-only">{t.common.loading}</span>
      <div className="space-y-3">
        <Skeleton className="h-5 w-full" />
        {Array.from({ length: rows }, (_, r) => (
          <div
            key={r}
            className="grid gap-4"
            style={{ gridTemplateColumns: `2fr repeat(${columns - 1}, 1fr)` }}
          >
            {Array.from({ length: columns }, (_, c) => (
              <Skeleton key={c} className="h-4" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function BlockSkeleton({ height = "h-72" }: { height?: string }) {
  return (
    <div className="card p-4" role="status" aria-live="polite">
      <span className="sr-only">{t.common.loading}</span>
      <Skeleton className={`w-full ${height}`} />
    </div>
  );
}
