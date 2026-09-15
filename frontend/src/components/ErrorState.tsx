import { ApiError } from "../api/client";
import { t } from "../i18n";
import { IconAlertTriangle } from "./icons";

function messageFor(error: unknown): {
  text: string;
  hint?: string;
  detail?: string;
} {
  if (error instanceof ApiError) {
    switch (error.kind) {
      case "network":
        return {
          text: t.errors.network(error.url),
          hint: t.errors.networkHint,
        };
      case "shape":
        return { text: t.errors.shape(error.url), detail: error.message };
      case "http":
        if (error.status === 503)
          return { text: t.errors.notBuilt, detail: error.detail };
        if (error.status === 404)
          return { text: t.errors.notFound, detail: error.detail };
        return {
          text: t.errors.http(error.status ?? 0, error.url),
          detail: error.detail,
        };
    }
  }
  return { text: error instanceof Error ? error.message : String(error) };
}

/** Clear error state: what failed, the URL that was tried, and a retry button. */
export function ErrorState({
  error,
  onRetry,
  compact = false,
}: {
  error: unknown;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const { text, hint, detail } = messageFor(error);
  return (
    <div
      role="alert"
      className={`card flex gap-3 border-high-fg/40 bg-high-bg/40 ${compact ? "p-3" : "p-5"}`}
    >
      <IconAlertTriangle size={22} className="mt-0.5 shrink-0 text-high-fg" />
      <div className="min-w-0 space-y-1">
        <p className="font-semibold text-high-fg">{t.errors.title}</p>
        <p className="break-words">{text}</p>
        {detail ? (
          <p className="break-words text-sm text-muted">{detail}</p>
        ) : null}
        {hint ? <p className="text-sm text-muted">{hint}</p> : null}
        {onRetry ? (
          <button type="button" className="btn mt-2" onClick={onRetry}>
            {t.common.retry}
          </button>
        ) : null}
      </div>
    </div>
  );
}
