/**
 * How many people wait for admission within 7, 14 and 30 days, and how many requests wait for the specialist.
 * The three waiting counts come from the synthetic queue and each carries the synthetic tag inline, on every
 * screen size; with the layer off they read as no data and the note says why.
 */
import { t } from "../../i18n";
import { fmtNumber } from "../../lib/format";
import { pendingTasks, waitingWithin } from "../sim/tasks";
import type { SimState } from "../sim/simulation";
import { SYNTHETIC_ENABLED } from "../synthetic";
import { SyntheticTag } from "./SyntheticState";

export function WaitingStrip({ state }: { state: SimState }) {
  const pending = pendingTasks(state).length;
  return (
    <div className="waiting-block">
      <dl className="waiting" aria-label={t.control.waiting.title}>
        {[7, 14, 30].map((days) => (
          <div key={days} className="waiting-cell is-synthetic">
            <dd>
              {fmtNumber(
                SYNTHETIC_ENABLED ? waitingWithin(state, days) : null,
                0,
              )}
            </dd>
            <dt>
              {t.control.waiting.title} {t.control.waiting.within(days)}{" "}
              <SyntheticTag />
            </dt>
          </div>
        ))}
        <div
          className={`waiting-cell is-pending ${pending ? "is-attention" : ""}`}
        >
          <dd>{fmtNumber(pending, 0)}</dd>
          <dt>{t.control.waiting.pending}</dt>
        </div>
      </dl>
      <p className="waiting-foot">
        <SyntheticTag />
        {SYNTHETIC_ENABLED
          ? t.control.waiting.note
          : t.control.syntheticOff.waiting}
      </p>
    </div>
  );
}
