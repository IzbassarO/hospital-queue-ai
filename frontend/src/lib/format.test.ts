import { describe, expect, it } from "vitest";

import {
  fmtDate,
  fmtDays,
  fmtInt,
  fmtNumber,
  fmtPercent,
  fmtTrend,
} from "./format";

// Intl uses a narrow no-break space as the Russian thousands separator
const normalise = (s: string) => s.replace(/[\u00a0\u202f]/g, " ");

describe("format", () => {
  it("uses Russian thousands separators and decimal comma", () => {
    expect(normalise(fmtInt(89545))).toBe("89 545");
    expect(normalise(fmtNumber(136515.6, 1))).toBe("136 515,6");
    expect(fmtDays(108.2)).toBe("108,2 дн.");
    expect(fmtPercent(0.6857)).toBe("68,6%");
    expect(fmtTrend(16.5)).toBe("+16,5 п.п./нед.");
    expect(fmtTrend(-2.04)).toBe("−2,0 п.п./нед.");
  });

  it("formats dates as dd.mm.yyyy without time-zone shifts", () => {
    expect(fmtDate("2025-03-31")).toBe("31.03.2025");
    expect(fmtDate("2025-01-01")).toBe("01.01.2025");
  });

  it("shows a dash for missing values", () => {
    expect(fmtDays(null)).toBe("—");
    expect(fmtPercent(undefined)).toBe("—");
    expect(fmtDate(null)).toBe("—");
  });
});
