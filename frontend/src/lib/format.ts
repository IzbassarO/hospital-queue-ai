/**
 * Display formatting: Russian number format (thousands separator, decimal comma), dates dd.mm.yyyy.
 * Every formatter returns the "no data" dash for null / undefined so tables never show "null" or "NaN".
 */
import { t } from "../i18n";

const LOCALE = "ru-RU";
const formatters = new Map<string, Intl.NumberFormat>();

function numberFormat(min: number, max: number): Intl.NumberFormat {
  const key = `${min}:${max}`;
  let f = formatters.get(key);
  if (!f) {
    f = new Intl.NumberFormat(LOCALE, {
      minimumFractionDigits: min,
      maximumFractionDigits: max,
    });
    formatters.set(key, f);
  }
  return f;
}

type Num = number | null | undefined;

const isMissing = (value: Num): value is null | undefined =>
  value === null || value === undefined || Number.isNaN(value);

/** 89545 → "89 545"; fixed number of decimals */
export function fmtNumber(value: Num, decimals = 0): string {
  return isMissing(value)
    ? t.common.noData
    : numberFormat(decimals, decimals).format(value);
}

/** Integers for counts (rounds forecast sums such as 53.1 → "53") */
export function fmtInt(value: Num): string {
  return fmtNumber(isMissing(value) ? value : Math.round(value), 0);
}

/** Days with one decimal: 108.2 → "108,2 дн." */
export function fmtDays(value: Num, decimals = 1): string {
  return isMissing(value)
    ? t.common.noData
    : `${fmtNumber(value, decimals)} ${t.units.days}`;
}

/** Share 0..1 → "68,6%" */
export function fmtPercent(share: Num, decimals = 1): string {
  return isMissing(share)
    ? t.common.noData
    : `${fmtNumber(share * 100, decimals)}%`;
}

/** Signed value: +16,5 / −2,1 (typographic minus) */
export function fmtSigned(value: Num, decimals = 1, suffix = ""): string {
  if (isMissing(value)) return t.common.noData;
  const rounded = Number(value.toFixed(decimals));
  const sign = rounded > 0 ? "+" : rounded < 0 ? "−" : "";
  return `${sign}${fmtNumber(Math.abs(rounded), decimals)}${suffix}`;
}

/** Excess queue trend in percentage points per week: "+16,5 п.п./нед." */
export function fmtTrend(value: Num): string {
  return isMissing(value)
    ? t.common.noData
    : fmtSigned(value, 1, ` ${t.units.ppPerWeek}`);
}

/** load_index 0–100 with one decimal */
export function fmtIndex(value: Num): string {
  return fmtNumber(value, 1);
}

/** "2025-03-31" → "31.03.2025" (string slicing: no time-zone shifts) */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return t.common.noData;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : iso;
}

/** "2026-09-15T13:11:55.887730Z" → "15.09.2026 13:11" in the viewer's time zone */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return t.common.noData;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Short axis label "31.03" */
export function fmtDayMonth(iso: string): string {
  return fmtDate(iso).slice(0, 5);
}
