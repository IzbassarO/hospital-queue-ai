/** Loading / missing-publication / error frame shared by every scene that needs the subject signal. */
import type { ReactNode } from "react";
import { ApiError } from "../../api/client";
import type { SignalView } from "../../api/operational-adapters";
import { t } from "../../i18n";
import type { useDemoSubject } from "../useDemoSubject";

export function SubjectState({
  subject,
  children,
}: {
  subject: ReturnType<typeof useDemoSubject>;
  children: (signal: SignalView) => ReactNode;
}) {
  if (subject.isPending)
    return (
      <div className="scene-state" role="status" aria-live="polite">
        <span className="pulse" aria-hidden="true" />
        {t.demo.loading}
      </div>
    );
  if (subject.error) {
    const status =
      subject.error instanceof ApiError ? subject.error.status : undefined;
    return (
      <div className="scene-state" role="alert">
        <h2>{status === 404 ? t.tower.noPublication : t.tower.unavailable}</h2>
        <p>
          {status === 404 ? t.tower.noPublicationHint : t.tower.unavailableHint}
        </p>
        <button type="button" className="btn-ghost" onClick={subject.refetch}>
          {t.common.retry}
        </button>
      </div>
    );
  }
  if (!subject.signal)
    return (
      <div className="scene-state" role="status">
        {t.demo.noSubject}
      </div>
    );
  return <>{children(subject.signal)}</>;
}

/** Same frame for secondary review-evidence queries; a 404 is an explicit "not published" state, not an error. */
export function EvidenceState<T>({
  isPending,
  error,
  data,
  notPublished,
  children,
}: {
  isPending: boolean;
  error: Error | null;
  data: T | undefined;
  notPublished: string;
  children: (data: T) => ReactNode;
}) {
  if (isPending)
    return (
      <div className="scene-state" role="status" aria-live="polite">
        <span className="pulse" aria-hidden="true" />
        {t.demo.loading}
      </div>
    );
  if (error) {
    const status = error instanceof ApiError ? error.status : undefined;
    return (
      <div className="scene-state" role={status === 404 ? "status" : "alert"}>
        <p>{status === 404 ? notPublished : t.tower.unavailableHint}</p>
      </div>
    );
  }
  if (data === undefined) return null;
  return <>{children(data)}</>;
}
