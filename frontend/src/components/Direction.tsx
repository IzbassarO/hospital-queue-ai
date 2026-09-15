import { t } from "../i18n";
import { IconArrowDown, IconArrowUp } from "./icons";

/** Effect direction: arrow icon with a text title (not colour alone). */
export function Direction({ direction }: { direction: string }) {
  const up = direction === "up";
  const Icon = up ? IconArrowUp : IconArrowDown;
  return (
    <span
      className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${
        up
          ? "border-high-fg/40 bg-high-bg text-high-fg"
          : "border-normal-fg/40 bg-normal-bg text-normal-fg"
      }`}
    >
      <Icon size={16} title={up ? t.why.up : t.why.down} />
    </span>
  );
}
