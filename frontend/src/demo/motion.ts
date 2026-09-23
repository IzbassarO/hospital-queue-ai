/** Motion utilities: every animation is finite and disabled under prefers-reduced-motion. */
import { useEffect, useState } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(QUERY).matches
      : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(QUERY);
    const onChange = () => setReduced(media.matches);
    media.addEventListener?.("change", onChange);
    return () => media.removeEventListener?.("change", onChange);
  }, []);
  return reduced;
}

/** Counts from 0 to `value` once (≈600 ms); renders the final value immediately when motion is reduced. */
export function useCountUp(
  value: number | null,
  reduced: boolean,
): number | null {
  const [animation, setAnimation] = useState<{
    target: number | null;
    progress: number;
  }>({ target: value, progress: reduced ? 1 : 0 });
  useEffect(() => {
    if (
      reduced ||
      value === null ||
      typeof requestAnimationFrame !== "function"
    )
      return;
    let frame = 0;
    const start = performance.now();
    const duration = 600;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      setAnimation({ target: value, progress });
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, reduced]);
  if (value === null) return null;
  if (reduced || typeof requestAnimationFrame !== "function") return value;
  const progress = animation.target === value ? animation.progress : 0;
  return value * (1 - Math.pow(1 - progress, 3));
}
