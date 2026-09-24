/** How many people wait for admission within 7, 14 and 30 days, and how many requests wait for the specialist. */
import { t } from "../../i18n";
import { fmtNumber } from "../../lib/format";
import { pendingTasks, waitingWithin } from "../sim/tasks";
import type { SimState } from "../sim/simulation";

export function WaitingStrip({ state }: { state: SimState }) {
  const pending = pendingTasks(state).length;
  return (
    <dl className="waiting" aria-label={t.control.waiting.title}>
      {[7, 14, 30].map((days) => (
        <div key={days} className="waiting-cell">
          <dd>{fmtNumber(waitingWithin(state, days), 0)}</dd>
          <dt>
            {t.control.waiting.title} {t.control.waiting.within(days)}
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
  );
}
