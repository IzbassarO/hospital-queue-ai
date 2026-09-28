/**
 * The queue section of hospital mode: the measured queue and the verification worklist as two tabs of one block.
 *
 * They are tabs rather than two stacked blocks on purpose. Side by side they would invite subtraction — "the
 * queue is 2 275, the worklist is 419, so the real queue is 1 856" — which is exactly the reading the worklist
 * publication forbids. One at a time, each keeps its own heading, its own totals and its own framing sentence.
 *
 * The second tab exists only while a worklist publication does.
 */
import { useState } from "react";
import { t } from "../i18n";
import type { ReferralEstimatesPublication } from "../api/referral-estimates";
import type { WorklistPublication } from "../api/verification-worklist";
import type { WaitingHospitalDetail } from "../api/waiting-list";
import { VerificationBlock } from "./VerificationBlock";
import { WaitingBlock } from "./WaitingBlock";

type Tab = "queue" | "worklist";

export function QueueSection({
  detail,
  profile,
  estimates,
  worklist,
}: {
  detail: WaitingHospitalDetail;
  profile: string | null;
  estimates: ReferralEstimatesPublication | null;
  worklist: WorklistPublication | null;
}) {
  const [tab, setTab] = useState<Tab>("queue");
  const active: Tab = worklist ? tab : "queue";

  return (
    <section className="hos-block" aria-label={t.hospital.waiting.title}>
      {worklist ? (
        <div
          className="hos-tabs"
          role="tablist"
          aria-label={t.hospital.tabs.label}
        >
          {(["queue", "worklist"] as const).map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              id={`hos-tab-${key}`}
              aria-selected={active === key}
              aria-controls={`hos-panel-${key}`}
              className={active === key ? "is-on" : ""}
              onClick={() => setTab(key)}
            >
              {t.hospital.tabs[key]}
            </button>
          ))}
        </div>
      ) : null}

      <div
        role={worklist ? "tabpanel" : undefined}
        id="hos-panel-queue"
        aria-labelledby={worklist ? "hos-tab-queue" : undefined}
        hidden={active !== "queue"}
      >
        <WaitingBlock detail={detail} profile={profile} estimates={estimates} />
      </div>
      {worklist ? (
        <div
          role="tabpanel"
          id="hos-panel-worklist"
          aria-labelledby="hos-tab-worklist"
          hidden={active !== "worklist"}
        >
          <VerificationBlock org={detail.org_code} publication={worklist} />
        </div>
      ) : null}
    </section>
  );
}
