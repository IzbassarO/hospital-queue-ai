/**
 * Plain CSV downloads for the report: UTF-8 with BOM so Excel opens Cyrillic correctly. A file may start with
 * comment lines (`# …`) that say what the rows are, so a synthetic export never travels unlabelled.
 */
export function toCsv(
  header: string[],
  rows: (string | number | null)[][],
  preamble: string[] = [],
): string {
  const cell = (v: string | number | null) => {
    const text = v === null || v === undefined ? "" : String(v);
    return /[";\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const comments = preamble.map((line) => `# ${line.replace(/\n/g, " ")}`);
  const table = [header, ...rows].map((r) => r.map(cell).join(";"));
  return [...comments, ...table].join("\n");
}

export function downloadCsv(filename: string, csv: string): void {
  // U+FEFF (byte-order mark) written as an escape, not a literal: Excel needs it to read the file as UTF-8.
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
