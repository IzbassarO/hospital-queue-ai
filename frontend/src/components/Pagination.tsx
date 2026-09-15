import { t } from "../i18n";

export function Pagination({
  total,
  limit,
  offset,
  onChange,
  busy = false,
}: {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
  busy?: boolean;
}) {
  if (total <= limit) {
    return <p className="text-sm text-muted">{t.common.total(total)}</p>;
  }
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav
      className="flex items-center justify-between gap-3"
      aria-label={t.common.pagination}
    >
      <p className="text-sm text-muted tabular-nums" aria-live="polite">
        {t.common.page(from, to, total)}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          className="btn"
          disabled={offset === 0 || busy}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          {t.common.prevPage}
        </button>
        <button
          type="button"
          className="btn"
          disabled={offset + limit >= total || busy}
          onClick={() => onChange(offset + limit)}
        >
          {t.common.nextPage}
        </button>
      </div>
    </nav>
  );
}
