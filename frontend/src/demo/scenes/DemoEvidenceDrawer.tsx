/**
 * Evidence drawer of the guided journey: the deterministic explanation in human language first, raw machine
 * tokens and identities behind a technical disclosure. Modal semantics mirror the operations drawer.
 */
import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { ApiError } from "../../api/client";
import { useExplanation } from "../../api/operational";
import { t } from "../../i18n";
import { fmtNumber } from "../../lib/format";
import {
  capabilityName,
  isTechnical,
  reasonLabel,
  statusLabel,
  translateList,
  translateSentence,
} from "../language";
import { Bullets, NonClaims, Technical } from "../primitives";

export function DemoEvidenceDrawer({
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
        e.stopPropagation();
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
    document.addEventListener("keydown", keydown, true);
    const root = document.getElementById("root");
    const wasInert = root?.inert ?? false;
    if (root) root.inert = true;
    return () => {
      document.removeEventListener("keydown", keydown, true);
      document.body.style.overflow = overflow;
      if (root) root.inert = wasInert;
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, []);
  return createPortal(
    <div
      className="drawer-backdrop demo-drawer-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        className="demo-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="demo-drawer-head">
          <h2 id={titleId}>{t.demo.understand.evidenceDrawer}</h2>
          <button
            ref={close}
            type="button"
            className="btn-ghost"
            onClick={onClose}
            aria-label={t.tower.close}
          >
            ×
          </button>
        </header>
        <div className="demo-drawer-body">
          {query.isPending ? (
            <p role="status">{t.demo.loading}</p>
          ) : query.isError ? (
            <div role="alert" className="scene-state">
              <p>
                {query.error instanceof ApiError && query.error.status === 404
                  ? t.tower.noPublicationHint
                  : t.tower.unavailableHint}
              </p>
            </div>
          ) : query.data.identity !== identity ? (
            <p role="status" className="notice-dark">
              {t.tower.publicationChanged}
            </p>
          ) : (
            <DrawerBody data={query.data} />
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function DrawerBody({
  data,
}: {
  data: NonNullable<ReturnType<typeof useExplanation>["data"]>;
}) {
  const why = translateList(data.why);
  const summary = translateSentence(data.summary);
  const isCode = (label: string) =>
    /^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$/.test(label);
  const evidence = data.evidence.map((e) => {
    if (isCode(e.label) || isTechnical(e.label))
      return {
        human: null,
        raw: `${e.label}${e.value !== t.common.noData ? ` = ${e.value}` : ""}`,
      };
    const translated = translateSentence(e.label);
    if (!translated) return { human: null, raw: `${e.label} = ${e.value}` };
    const value =
      e.value === t.common.noData
        ? ""
        : isTechnical(e.value)
          ? statusLabel(e.value)
          : Number.isFinite(Number(e.value))
            ? fmtNumber(Number(e.value), 1)
            : e.value;
    return { human: value ? `${translated}: ${value}` : translated, raw: null };
  });
  const limitations = translateList(data.limitations);
  const questions = translateList(data.questions);
  const reasonCodes = data.evidence.map((e) => e.label).filter(isCode);
  return (
    <>
      <p className="panel-eyebrow">
        {statusLabel(
          data.generation === t.tower.deterministic
            ? "DETERMINISTIC"
            : data.generation === t.tower.deterministicFallback
              ? "DETERMINISTIC_FALLBACK"
              : "NARRATED",
        )}
      </p>
      <section className="drawer-section">
        <h3>{t.tower.summary}</h3>
        <p className="drawer-summary">
          {summary ?? t.demo.language.unknownFact}
        </p>
      </section>
      <section className="drawer-section">
        <h3>{t.demo.understand.whyTitle}</h3>
        <Bullets
          items={[...new Set([...reasonCodes.map(reasonLabel), ...why.human])]}
          tone="check"
        />
      </section>
      <section className="drawer-section">
        <h3>{t.demo.understand.keyEvidence}</h3>
        <Bullets
          items={evidence
            .map((e) => e.human)
            .filter((v): v is string => v !== null)}
        />
        <p className="drawer-line">
          {translateSentence(data.uncertainty) ?? t.tower.uncertainty}
        </p>
        <p className="drawer-line">
          {t.tower.support}: {statusLabel(data.supportStatus)}
        </p>
      </section>
      <NonClaims title={t.tower.limitations} items={limitations.human} />
      <section className="drawer-section">
        <h3>{t.demo.understand.questions}</h3>
        <Bullets items={questions.human} />
      </section>
      <section className="drawer-section">
        <h3>{t.tower.assurance}</h3>
        <Bullets
          items={data.capabilities.map(
            (c) => `${capabilityName(c.id)} · ${c.evidence} · ${c.acceptance}`,
          )}
        />
      </section>
      <Technical
        title={t.demo.understand.technical}
        items={[
          ...data.provenance,
          ...evidence
            .filter((e) => e.raw !== null)
            .map((e, i) => ({ label: `evidence ${i + 1}`, value: e.raw! })),
        ]}
        lines={[
          ...why.technical,
          ...limitations.technical,
          ...questions.technical,
        ]}
      />
    </>
  );
}
