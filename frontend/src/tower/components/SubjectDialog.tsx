/** The modal around SubjectContent: closes on Escape, on the ×, on the cancel button and on a click outside. */
import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { t } from "../../i18n";
import { closeExplorer } from "../ui";
import type {
  DecisionAction,
  PatientAction,
  SimState,
} from "../sim/simulation";
import type { SubjectView } from "../subject";
import { SubjectContent } from "./SubjectContent";

export function SubjectDialog({
  view,
  state,
  onDecideAlert,
  onDecidePatient,
  onClose,
}: {
  view: SubjectView;
  state: SimState;
  onDecideAlert: (id: string, action: DecisionAction, comment: string) => void;
  onDecidePatient: (id: string, action: PatientAction, comment: string) => void;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useEffect(() => {
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    const keydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
      if (e.key !== "Tab") return;
      const items = Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input, textarea, [tabindex="0"]',
        ) ?? [],
      );
      const first = items[0],
        last = items.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", keydown, true);
    return () => {
      document.removeEventListener("keydown", keydown, true);
      document.body.style.overflow = overflow;
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, [onClose]);
  return createPortal(
    <div
      className="drawer-backdrop decision-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        className="decision subject-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <button
          ref={closeButton}
          type="button"
          className="dialog-close"
          aria-label={t.control.decision.close}
          onClick={onClose}
        >
          ×
        </button>
        <span id={titleId} className="sr-only">
          {view.patient
            ? t.control.patientDecision.title
            : t.control.decision.title}
        </span>
        <SubjectContent
          view={view}
          state={state}
          onDecideAlert={onDecideAlert}
          onDecidePatient={onDecidePatient}
          onClose={() => {
            closeExplorer();
            onClose();
          }}
          compact
        />
      </div>
    </div>,
    document.body,
  );
}
