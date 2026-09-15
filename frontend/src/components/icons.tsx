/** Inline SVG icons (stroke style, currentColor). Decorative by default: pass `title` to make one meaningful. */
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { title?: string; size?: number };

function Icon({
  title,
  size = 16,
  children,
  ...rest
}: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

export const IconAlertTriangle = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4M12 17h.01" />
  </Icon>
);

export const IconAlertCircle = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9.5" />
    <path d="M12 7.5v5M12 16.5h.01" />
  </Icon>
);

export const IconCheck = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9.5" />
    <path d="m8 12.5 2.8 2.8L16.5 9.5" />
  </Icon>
);

export const IconMinus = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9.5" strokeDasharray="3 3" />
    <path d="M8 12h8" />
  </Icon>
);

export const IconArrowUp = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />
  </Icon>
);

export const IconArrowDown = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 5v14M18.5 12.5 12 19l-6.5-6.5" />
  </Icon>
);

export const IconInfo = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9.5" />
    <path d="M12 11v5.5M12 7.5h.01" />
  </Icon>
);

export const IconChevronRight = (p: IconProps) => (
  <Icon {...p}>
    <path d="m9 5 7 7-7 7" />
  </Icon>
);

export const IconChevronDown = (p: IconProps) => (
  <Icon {...p}>
    <path d="m5 9 7 7 7-7" />
  </Icon>
);

export const IconSort = (
  p: IconProps & { sortDirection: "asc" | "desc" | null },
) => {
  const { sortDirection: direction, ...rest } = p;
  return (
    <Icon {...rest}>
      <path d="m8 9 4-4 4 4" opacity={direction === "desc" ? 0.25 : 1} />
      <path d="m16 15-4 4-4-4" opacity={direction === "asc" ? 0.25 : 1} />
    </Icon>
  );
};

export const IconUser = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21a8 8 0 0 1 16 0" />
  </Icon>
);
