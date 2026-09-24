/** Plain CSV downloads for the report: UTF-8 with BOM so Excel opens Cyrillic correctly. Nothing fancy. */
export function toCsv(
  header: string[],
  rows: (string | number | null)[][],
): string {
  const cell = (v: string | number | null) => {
    const text = v === null || v === undefined ? "" : String(v);
    return /[";\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [header, ...rows].map((r) => r.map(cell).join(";")).join("\n");
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
