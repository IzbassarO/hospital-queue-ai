import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { useExplanation } from "../../api/operational";
import { t } from "../../i18n";
import {
  EvidenceState,
  Facts,
  Limitations,
  Lines,
  Notice,
  Provenance,
  SupportBadge,
} from "./Evidence";

/** Modal dialog: focus trap, Escape, scroll lock and focus restoration. */
export function ExplanationDrawer({
  signalId,
  identity,
  onClose,
}: {
  signalId: string;
  identity: string;
  onClose: () => void;
}) {
  const query = useExplanation(signalId);
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    close.current?.focus();
    const keydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseRef.current();
      }
      if (e.key !== "Tab") return;
      const elements = Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], summary, [tabindex="0"]',
        ) ?? [],
      ).filter(
        (el) => !el.closest("details:not([open])") || el.tagName === "SUMMARY",
      );
      const first = elements[0],
        last = elements.at(-1);
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    // inert protects the background from keyboard and screen-reader navigation.
    const root = document.getElementById("root");
    const wasInert = root?.inert ?? false;
    if (root) root.inert = true;
    return () => {
      document.removeEventListener("keydown", keydown);
      document.body.style.overflow = overflow;
      if (root) root.inert = wasInert;
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, []);
  return createPortal(
    <div
      className="drawer-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        className="evidence-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="drawer-header">
          <h2 id={titleId} className="text-xl font-semibold">
            {t.tower.explain}
          </h2>
          <button
            ref={close}
            className="btn"
            onClick={onClose}
            aria-label={t.tower.close}
          >
            ×
          </button>
        </header>
        <div className="space-y-5 p-6">
          <EvidenceState query={query}>
            {(data) =>
              data.identity !== identity ? (
                <Notice>{t.tower.publicationChanged}</Notice>
              ) : (
                <>
                  <p className="eyebrow">{data.generation}</p>
                  <section>
                    <h3 className="font-semibold">{t.tower.summary}</h3>
                    <p className="mt-2 text-lg">{data.summary}</p>
                  </section>
                  <section>
                    <h3 className="mb-2 font-semibold">{t.tower.reasons}</h3>
                    <Lines items={data.why} />
                  </section>
                  <section>
                    <h3 className="mb-2 font-semibold">{t.tower.evidence}</h3>
                    <Facts items={data.evidence} />
                  </section>
                  <section>
                    <h3 className="mb-2 font-semibold">
                      {t.tower.uncertainty}
                    </h3>
                    <p>{data.uncertainty}</p>
                  </section>
                  <section className="space-y-2">
                    <h3 className="font-semibold">{t.tower.support}</h3>
                    <SupportBadge value={data.supportStatus} />
                    <p>{data.support}</p>
                    <p>
                      {t.tower.fallback}: {data.fallback}
                    </p>
                  </section>
                  <Limitations items={data.limitations} />
                  <section>
                    <h3 className="mb-2 font-semibold">{t.tower.questions}</h3>
                    <Lines items={data.questions} />
                  </section>
                  <section className="space-y-2">
                    <h3 className="font-semibold">{t.tower.assurance}</h3>
                    {data.capabilities.map((c) => (
                      <div key={c.id} className="space-y-2">
                        <p>
                          <a className="link" href={`/assurance#${c.id}`}>
                            {c.id}
                          </a>{" "}
                          · {c.evidence} · {c.acceptance} · {c.consumption}
                        </p>
                        <Lines items={c.governance} />
                      </div>
                    ))}
                  </section>
                  <Provenance items={data.provenance} />
                </>
              )
            }
          </EvidenceState>
        </div>
      </div>
    </div>,
    document.body,
  );
}
