import { type ReactNode, useId, useState } from "react";

import { IconInfo } from "./icons";

/**
 * Accessible tooltip: opens on hover and on keyboard focus, closes on blur / Escape. The trigger is a button, so it
 * is reachable by Tab and announced with the tooltip text via aria-describedby.
 */
export function InfoTip({
  label,
  children,
  align = "left",
  width = "w-96",
}: {
  label: string;
  children: ReactNode;
  align?: "left" | "right";
  width?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      className="relative inline-flex align-middle"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="inline-flex items-center rounded-full p-0.5 text-muted hover:text-accent-700"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        <IconInfo size={18} />
      </button>
      {open ? (
        <span
          role="tooltip"
          id={id}
          className={`absolute top-full z-30 mt-2 ${width} rounded-md border border-line bg-white p-3 text-left text-sm font-normal leading-relaxed text-ink shadow-lg ${
            align === "right" ? "right-0" : "left-0"
          }`}
        >
          {children}
        </span>
      ) : null}
    </span>
  );
}
