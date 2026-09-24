/** Minimal line glyphs of the journey (1.5px strokes, currentColor). */
import type { SVGProps } from "react";

type Props = SVGProps<SVGSVGElement> & { size?: number };
const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
});

export const GlyphReferral = ({ size = 20, ...p }: Props) => (
  <svg {...base(size)} {...p}>
    <path d="M7 3.5h7l4 4V20a.5.5 0 0 1-.5.5h-10A.5.5 0 0 1 7 20V3.5Z" />
    <path d="M14 3.5v4h4M9.5 12h5M9.5 15.5h5" />
  </svg>
);
export const GlyphFlow = ({ size = 20, ...p }: Props) => (
  <svg {...base(size)} {...p}>
    <path d="M3 8c3 0 3 3 6 3s3-3 6-3 3 3 6 3M3 15c3 0 3 3 6 3s3-3 6-3 3 3 6 3" />
  </svg>
);
export const GlyphForecast = ({ size = 20, ...p }: Props) => (
  <svg {...base(size)} {...p}>
    <path d="M3.5 18.5 9 12l4 3 7-8" />
    <path d="M16.5 7H20v3.5" />
    <path d="M3.5 21h17" strokeOpacity="0.4" />
  </svg>
);
export const GlyphSignal = ({ size = 20, ...p }: Props) => (
  <svg {...base(size)} {...p}>
    <circle cx="12" cy="12" r="2.2" />
    <path d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14" />
  </svg>
);
export const GlyphEvidence = ({ size = 20, ...p }: Props) => (
  <svg {...base(size)} {...p}>
    <path d="M12 3.5 4.5 7v5c0 4.5 3.2 7.6 7.5 8.5 4.3-.9 7.5-4 7.5-8.5V7L12 3.5Z" />
    <path d="m9 12 2 2 4-4.5" />
  </svg>
);
export const GlyphHuman = ({ size = 20, ...p }: Props) => (
  <svg {...base(size)} {...p}>
    <circle cx="12" cy="8" r="3.5" />
    <path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" />
  </svg>
);
export const GlyphAudit = ({ size = 20, ...p }: Props) => (
  <svg {...base(size)} {...p}>
    <rect x="4" y="4" width="16" height="16" rx="3" />
    <path d="M8 9h8M8 12.5h8M8 16h5" />
  </svg>
);
export const GlyphPlay = ({ size = 16, ...p }: Props) => (
  <svg {...base(size)} {...p} fill="currentColor" stroke="none">
    <path d="M8 5.5v13l10-6.5-10-6.5Z" />
  </svg>
);
export const GlyphPause = ({ size = 16, ...p }: Props) => (
  <svg {...base(size)} {...p} fill="currentColor" stroke="none">
    <path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" />
  </svg>
);
export const GlyphReplay = ({ size = 16, ...p }: Props) => (
  <svg {...base(size)} {...p}>
    <path d="M4 12a8 8 0 1 0 2.5-5.8" />
    <path d="M4 4.5v4h4" />
  </svg>
);
export const GlyphArrow = ({ size = 16, ...p }: Props) => (
  <svg {...base(size)} {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </svg>
);
export const GlyphMark = ({ size = 22, ...p }: Props) => (
  <svg {...base(size)} {...p} strokeWidth={2}>
    <path d="M4 14c2.5 0 3.5-4 6-4s3.5 4 6 4 2.5-2 4-2" />
  </svg>
);
export const GlyphBell = ({ size = 18, ...p }: Props) => (
  <svg
    viewBox="0 0 24 24"
    width={size}
    height={size}
    fill="none"
    stroke="currentColor"
    strokeWidth="1.7"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    {...p}
  >
    <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
    <path d="M10 20a2 2 0 0 0 4 0" />
  </svg>
);
