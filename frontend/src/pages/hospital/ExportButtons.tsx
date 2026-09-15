import { useState } from "react";

import { api, ApiError } from "../../api/client";
import { IconDownload } from "../../components/icons";
import { t } from "../../i18n";

const FORMATS = [
  { format: "xlsx", label: t.export.xlsx },
  { format: "pdf", label: t.export.pdf },
] as const;

/** «Скачать отчёт»: fetches the file with the API key (a plain link cannot send the header) and saves it. */
export function ExportButtons({
  org,
  profile,
}: {
  org: string;
  profile: string;
}) {
  const [busy, setBusy] = useState<"xlsx" | "pdf" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const download = async (format: "xlsx" | "pdf") => {
    setBusy(format);
    setError(null);
    try {
      const file = await api.exportCard(org, profile, format);
      const url = URL.createObjectURL(file.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? (cause.detail ?? cause.message)
          : String(cause),
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="group"
      aria-label={t.export.title}
    >
      <span className="text-sm font-medium text-muted">{t.export.title}:</span>
      {FORMATS.map(({ format, label }) => (
        <button
          key={format}
          type="button"
          className="btn"
          disabled={busy !== null}
          aria-busy={busy === format}
          onClick={() => void download(format)}
        >
          <IconDownload size={16} />
          {busy === format ? t.export.downloading : label}
        </button>
      ))}
      {error ? (
        <p role="alert" className="text-sm font-medium text-high-fg">
          {t.export.failed}: {error}
        </p>
      ) : null}
    </div>
  );
}
