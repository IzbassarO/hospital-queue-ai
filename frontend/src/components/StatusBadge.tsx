import type { Status } from "../api/types";
import { t } from "../i18n";
import {
  IconAlertCircle,
  IconAlertTriangle,
  IconCheck,
  IconMinus,
} from "./icons";

const STYLES: Record<Status, { className: string; Icon: typeof IconCheck }> = {
  high: {
    className: "bg-high-bg text-high-fg border-high-fg/40",
    Icon: IconAlertTriangle,
  },
  elevated: {
    className: "bg-elevated-bg text-elevated-fg border-elevated-fg/40",
    Icon: IconAlertCircle,
  },
  normal: {
    className: "bg-normal-bg text-normal-fg border-normal-fg/30",
    Icon: IconCheck,
  },
  insufficient_data: {
    className: "bg-nodata-bg text-nodata-fg border-nodata-fg/30",
    Icon: IconMinus,
  },
};

/** Load status: colour + icon + text, never colour alone. */
export function StatusBadge({
  status,
  size = "md",
}: {
  status: Status;
  size?: "md" | "lg";
}) {
  const { className, Icon } = STYLES[status];
  const large = size === "lg";
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border font-semibold ${className} ${
        large ? "px-3 py-1 text-base" : "px-2 py-0.5 text-sm"
      }`}
      title={t.statusLong[status]}
    >
      <Icon size={large ? 18 : 15} />
      {t.status[status]}
    </span>
  );
}
