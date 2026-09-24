/**
 * Onboarding: a small card that walks along the page, one step at a time. Anchors are `data-tour` attributes;
 * a step whose anchor is missing on the current page is skipped. Mounted = open; the parent unmounts it to close.
 */
import { useCallback, useEffect, useState } from "react";
import { t } from "../../i18n";
import { markTourSeen } from "../tour-state";

export type TourStepId =
  "lead" | "waiting" | "play" | "feed" | "map" | "tasks" | "notifications";
const ORDER: TourStepId[] = [
  "lead",
  "waiting",
  "play",
  "feed",
  "map",
  "tasks",
  "notifications",
];

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

export function Tour({ onClose }: { onClose: () => void }) {
  // Anchors can appear after data loads: re-read them on every render (a handful of querySelector calls).
  const steps = ORDER.filter(
    (id) => document.querySelector(`[data-tour="${id}"]`) !== null,
  );
  const [index, setIndex] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const step = steps[index];
  const finish = useCallback(() => {
    markTourSeen();
    onClose();
  }, [onClose]);
  const next = useCallback(() => {
    if (index >= steps.length - 1) finish();
    else setIndex(index + 1);
  }, [index, steps.length, finish]);
  const back = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  useEffect(() => {
    if (!step) return;
    const el = document.querySelector<HTMLElement>(`[data-tour="${step}"]`);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    const measure = () => {
      const r = el.getBoundingClientRect();
      setBox({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    const frame = window.requestAnimationFrame(measure);
    const timer = window.setTimeout(measure, 450);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish();
      if (e.key === "ArrowRight") next();
      if (e.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [finish, next, back]);
  if (!step) return null;
  const copy = t.control.tour.steps[step];
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const cardW = Math.min(360, vw - 32);
  const below = box ? box.top + box.height + 12 : 80;
  const placeBelow = box ? below + 220 < vh : true;
  const top = box ? (placeBelow ? below : Math.max(16, box.top - 232)) : 80;
  const left = box
    ? Math.min(Math.max(16, box.left), vw - cardW - 16)
    : Math.max(16, (vw - cardW) / 2);
  return (
    <div className="tour" role="dialog" aria-label={t.control.tour.title}>
      {box ? (
        <div
          className="tour-spot"
          style={{
            top: box.top - 8,
            left: box.left - 8,
            width: box.width + 16,
            height: box.height + 16,
          }}
          aria-hidden="true"
        />
      ) : null}
      <div className="tour-card" style={{ top, left, width: cardW }}>
        <p className="tour-step">
          {t.control.tour.stepOf(index + 1, steps.length)}
        </p>
        <h2>{copy.title}</h2>
        <p>{copy.body}</p>
        <div className="tour-actions">
          <button type="button" className="btn-link" onClick={finish}>
            {t.control.tour.skip}
          </button>
          <span className="tour-spacer" />
          {index > 0 ? (
            <button type="button" className="btn-ghost btn-sm" onClick={back}>
              {t.control.tour.back}
            </button>
          ) : null}
          <button type="button" className="btn-accent btn-sm" onClick={next}>
            {index >= steps.length - 1
              ? t.control.tour.done
              : t.control.tour.next}
          </button>
        </div>
      </div>
    </div>
  );
}
