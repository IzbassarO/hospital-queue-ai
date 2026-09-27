/**
 * Urgency of attention: the product's own reading of a published signal from its severity, lead time, flow size
 * and support. Published severity is shown as published; urgency applies the materiality floor on top of it.
 */
export type Urgency = "high" | "medium" | "planned";

/**
 * Below this daily flow a series is too small for "high" attention, whatever its published severity: a hospital
 * that usually sees one referral a week is not in trouble because the forecast says two.
 */
export const URGENCY_FLOOR_PER_DAY = 1;

export function urgencyOf(
  severity: string,
  leadDays: number | null,
  central: number | null = null,
  support: string | null = null,
): Urgency {
  if (central !== null && central < URGENCY_FLOOR_PER_DAY) return "planned";
  const weak = support !== null && support !== "DIRECT_SUPPORTED";
  if (severity === "HIGH" && leadDays !== null && leadDays <= 2 && !weak)
    return "high";
  if (severity === "HIGH" || (leadDays !== null && leadDays <= 5))
    return "medium";
  return "planned";
}
