import { Fragment, type ReactNode, useMemo, useState } from "react";

import { t } from "../i18n";
import { IconSort } from "./icons";

export interface Column<Row> {
  key: string;
  header: ReactNode;
  /** plain-text header for aria labels when `header` is not a string */
  headerText?: string;
  align?: "left" | "right" | "center";
  width?: string;
  render: (row: Row) => ReactNode;
  /** enables client-side sorting on this column; null values always sort last */
  sortValue?: (row: Row) => number | string | null;
}

export type SortState = { key: string; direction: "asc" | "desc" };

/**
 * Table with a sticky header, right-aligned numbers and optional client-side sorting. Rows are clickable when
 * `onRowClick` is given (the row also needs a real link inside for keyboard and middle-click users).
 */
export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  caption,
  initialSort,
  onRowClick,
  expandedRow,
  maxHeight = "max-h-[70vh]",
  empty,
}: {
  columns: Column<Row>[];
  rows: Row[];
  rowKey: (row: Row) => string;
  caption?: string;
  initialSort?: SortState;
  onRowClick?: (row: Row) => void;
  /** content rendered in a full-width row under the row, or null */
  expandedRow?: (row: Row) => ReactNode | null;
  maxHeight?: string;
  empty?: string;
}) {
  const [sort, setSort] = useState<SortState | undefined>(initialSort);

  const sorted = useMemo(() => {
    const column = sort && columns.find((c) => c.key === sort.key);
    if (!sort || !column?.sortValue) return rows;
    const factor = sort.direction === "asc" ? 1 : -1;
    const value = column.sortValue;
    return [...rows].sort((a, b) => {
      const va = value(a);
      const vb = value(b);
      if (va === null && vb === null) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      if (typeof va === "string" && typeof vb === "string")
        return factor * va.localeCompare(vb, "ru");
      return factor * ((va as number) - (vb as number));
    });
  }, [rows, sort, columns]);

  const toggle = (column: Column<Row>) => {
    setSort((current) =>
      current?.key === column.key
        ? {
            key: column.key,
            direction: current.direction === "desc" ? "asc" : "desc",
          }
        : {
            key: column.key,
            direction: column.align === "right" ? "desc" : "asc",
          },
    );
  };

  const alignClass = (align: Column<Row>["align"]) =>
    align === "right"
      ? "text-right"
      : align === "center"
        ? "text-center"
        : "text-left";

  return (
    <div className={`card overflow-auto ${maxHeight}`}>
      <table className="w-full border-collapse text-[15px]">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => {
              const active = sort?.key === column.key;
              const ariaSort = active
                ? sort.direction === "asc"
                  ? "ascending"
                  : "descending"
                : undefined;
              const label =
                column.headerText ??
                (typeof column.header === "string"
                  ? column.header
                  : column.key);
              return (
                <th
                  key={column.key}
                  scope="col"
                  aria-sort={
                    column.sortValue ? (ariaSort ?? "none") : undefined
                  }
                  className={`sticky top-0 z-10 border-b-2 border-line bg-[#eef1f5] px-3 py-2.5 text-sm font-semibold text-ink ${alignClass(
                    column.align,
                  )} ${column.width ?? ""}`}
                >
                  {column.sortValue ? (
                    <button
                      type="button"
                      onClick={() => toggle(column)}
                      className={`inline-flex items-center gap-1 hover:text-accent-700 ${
                        column.align === "right" ? "flex-row-reverse" : ""
                      }`}
                      aria-label={t.common.sortBy(label)}
                    >
                      <span>{column.header}</span>
                      <IconSort
                        size={14}
                        sortDirection={active ? sort.direction : null}
                        className={active ? "text-accent-700" : "text-muted"}
                      />
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-6 text-center text-muted"
              >
                {empty}
              </td>
            </tr>
          ) : (
            sorted.map((row) => {
              const expanded = expandedRow?.(row);
              return (
                <Fragment key={rowKey(row)}>
                  <tr
                    className={`border-b border-line/70 ${onRowClick ? "cursor-pointer hover:bg-accent-50" : ""} ${
                      expanded ? "bg-accent-50/60" : ""
                    }`}
                    onClick={
                      onRowClick
                        ? (e) => {
                            // clicks on links, buttons and form controls keep their own behaviour
                            if (
                              (e.target as HTMLElement).closest(
                                "a, button, input, select, textarea",
                              )
                            )
                              return;
                            onRowClick(row);
                          }
                        : undefined
                    }
                  >
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className={`px-3 py-2.5 align-top ${alignClass(column.align)} ${
                          column.align === "right"
                            ? "tabular-nums whitespace-nowrap"
                            : ""
                        }`}
                      >
                        {column.render(row)}
                      </td>
                    ))}
                  </tr>
                  {expanded ? (
                    <tr className="border-b border-line bg-accent-50/40">
                      <td colSpan={columns.length} className="px-3 py-3">
                        {expanded}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
