import type { LoadIndexComponents } from "../api/types";
import { t } from "../i18n";
import { fmtNumber } from "../lib/format";

// weights of docs/api.md §3 (ml/configs/serving.yaml → load_index.weights); the API returns the scores only
const PARTS: {
  key: keyof LoadIndexComponents;
  label: string;
  weight: number;
}[] = [
  { key: "backlog_score", label: t.loadIndex.backlog, weight: 60 },
  { key: "refusal_score", label: t.loadIndex.refusal, weight: 25 },
  { key: "trend_score", label: t.loadIndex.trend, weight: 15 },
];

/** The three 0–1 scores behind load_index as small labelled bars (value printed, not only drawn). */
export function LoadIndexBars({
  components,
}: {
  components: LoadIndexComponents;
}) {
  return (
    <ul className="w-72 space-y-1.5" aria-label={t.loadIndex.components}>
      {PARTS.map(({ key, label, weight }) => {
        const score = components[key];
        return (
          <li
            key={key}
            className="grid grid-cols-[1fr_auto] items-center gap-x-2 text-sm"
          >
            <span className="text-ink">
              {label}{" "}
              <span className="text-muted">({t.loadIndex.weight(weight)})</span>
            </span>
            <span className="num font-semibold">
              {score === null ? t.common.noData : fmtNumber(score, 2)}
            </span>
            <span
              className="col-span-2 h-2 overflow-hidden rounded-full bg-[#e3e8ee]"
              role="meter"
              aria-label={label}
              aria-valuemin={0}
              aria-valuemax={1}
              aria-valuenow={score ?? undefined}
              aria-valuetext={
                score === null
                  ? t.loadIndex.undefinedComponent
                  : fmtNumber(score, 2)
              }
            >
              <span
                className="block h-full rounded-full bg-accent-700"
                style={{ width: `${Math.round((score ?? 0) * 100)}%` }}
              />
            </span>
          </li>
        );
      })}
    </ul>
  );
}
