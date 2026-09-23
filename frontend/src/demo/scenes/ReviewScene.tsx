/** Scene 4 — REVIEW: retrospective mathematical alternatives for human review (or the engine's abstention). */
import { useState } from "react";
import { t } from "../../i18n";
import { fmtNumber } from "../../lib/format";
import {
  useAlternativeSet,
  useAlternativeSets,
  useSignalAlternatives,
  type AlternativeSet,
} from "../api";
import { TransferChart } from "../charts/TransferChart";
import { abstentionLabel, percent1, statusLabel } from "../language";
import {
  Arrow,
  Bullets,
  NonClaims,
  Panel,
  Scene,
  SeverityPill,
  Stat,
  StatGrid,
  Technical,
} from "../primitives";
import { EvidenceState, SubjectState } from "./SubjectState";
import { hospitalName, useDemoSubject } from "../useDemoSubject";

export function ReviewScene() {
  const subject = useDemoSubject();
  const signal = subject.signal;
  const own = useSignalAlternatives(signal?.id ?? "");
  const regional = useAlternativeSets({
    origin: signal?.origin,
    region: signal?.region ?? undefined,
    with_alternatives: true,
    limit: 50,
    offset: 0,
  });
  const [chosen, setChosen] = useState<string | null>(null);
  // Deterministic example rule: same region and origin, lowest donor rank, largest budget; never the browser's pick.
  const candidates = [...(regional.data?.items ?? [])].sort(
    (a, b) =>
      (a.donor.inbox_rank ?? Number.MAX_SAFE_INTEGER) -
        (b.donor.inbox_rank ?? Number.MAX_SAFE_INTEGER) ||
      b.budget - a.budget ||
      a.set_id.localeCompare(b.set_id),
  );
  const exampleId = chosen ?? candidates[0]?.set_id ?? "";
  const example = useAlternativeSet(exampleId);
  return (
    <SubjectState subject={subject}>
      {() => (
        <Scene
          kicker={t.demo.scenes.review.kicker}
          title={t.demo.review.title}
          lead={<p className="scene-sub">{t.demo.review.subtitle}</p>}
        >
          <div className="scene-grid review-grid">
            <div className="review-own">
              <Panel
                tone="glass"
                eyebrow={t.demo.review.forThisSignal}
                title={`${subject.names.hospital} · ${subject.names.profile}`}
              >
                <EvidenceState
                  isPending={own.isPending}
                  error={own.error}
                  data={own.data}
                  notPublished={t.demo.review.notPublished}
                >
                  {(data) => (
                    <OwnSets
                      sets={data.sets}
                      names={(code) =>
                        hospitalName(subject.dictionaries?.organizations, code)
                      }
                    />
                  )}
                </EvidenceState>
              </Panel>
              <NonClaims
                title={t.demo.understand.notClaimTitle}
                items={t.demo.review.nonClaims}
              />
            </div>
            <div className="review-example">
              <Panel
                eyebrow={t.demo.review.exampleTitle}
                title={subject.names.region}
              >
                <p className="panel-lead">{t.demo.review.exampleLead}</p>
                {candidates.length === 0 && !regional.isPending ? (
                  <p className="scene-state" role="status">
                    {t.demo.review.noExample}
                  </p>
                ) : (
                  <EvidenceState
                    isPending={example.isPending || regional.isPending}
                    error={example.error ?? regional.error}
                    data={example.data}
                    notPublished={t.demo.review.noExample}
                  >
                    {(set) => (
                      <ExampleSet
                        set={set}
                        names={(code) =>
                          hospitalName(
                            subject.dictionaries?.organizations,
                            code,
                          )
                        }
                        profileName={(code) =>
                          subject.dictionaries?.profiles.find(
                            (p) => p.code === code,
                          )?.name ?? code
                        }
                      />
                    )}
                  </EvidenceState>
                )}
                {candidates.length > 1 ? (
                  <label className="example-switch">
                    <span>{t.demo.review.chooseExample}</span>
                    <select
                      className="field-dark"
                      value={exampleId}
                      onChange={(e) => setChosen(e.target.value)}
                    >
                      {candidates.map((c) => (
                        <option key={c.set_id} value={c.set_id}>
                          #{c.donor.inbox_rank ?? "—"} ·{" "}
                          {hospitalName(
                            subject.dictionaries?.organizations,
                            c.donor.org_code,
                          )}{" "}
                          ·{" "}
                          {subject.dictionaries?.profiles.find(
                            (p) => p.code === c.donor.profile_code,
                          )?.name ?? c.donor.profile_code}{" "}
                          · {t.demo.review.budget(c.budget)}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </Panel>
            </div>
          </div>
        </Scene>
      )}
    </SubjectState>
  );
}

function OwnSets({
  sets,
  names,
}: {
  sets: AlternativeSet[];
  names: (code: string) => string;
}) {
  const sorted = [...sets].sort((a, b) => a.budget - b.budget);
  const withAlternatives = sorted.filter((s) => s.alternatives.length);
  const first = sorted[0];
  if (!first) return null;
  const codes = [...new Set(sorted.flatMap((s) => s.abstention_codes))];
  return (
    <>
      {withAlternatives.length === 0 ? (
        <>
          <h3 className="review-verdict">{t.demo.review.abstainedTitle}</h3>
          <p className="panel-lead">{t.demo.review.abstainedLead}</p>
        </>
      ) : null}
      <StatGrid>
        <Stat
          label={t.demo.review.budgets}
          text={sorted.map((s) => t.demo.review.budget(s.budget)).join(" · ")}
        />
        <Stat
          label={t.demo.review.considered}
          value={first.receiver_candidates_considered}
          decimals={0}
          hint={`${fmtNumber(first.receiver_candidates_eligible, 0)} ${t.demo.review.eligible}`}
        />
        <Stat
          label={t.demo.review.minimumFraction}
          text={
            first.donor_minimum_transfer_fraction === null
              ? t.common.noData
              : percent1(first.donor_minimum_transfer_fraction)
          }
          hint={t.demo.review.minimumHint}
        />
      </StatGrid>
      {codes.length ? (
        <>
          <h4 className="review-subtitle">{t.demo.review.reasonsTitle}</h4>
          <Bullets items={codes.map(abstentionLabel)} />
        </>
      ) : null}
      {withAlternatives.map((s) => (
        <div key={s.set_id} className="own-alternatives">
          <h4 className="review-subtitle">{t.demo.review.budget(s.budget)}</h4>
          <Bullets
            items={s.alternatives.map(
              (a) =>
                `${names(a.receiver.org_code)} · ${t.demo.review.fraction} ${percent1(a.transfer_fraction)} · ${statusLabel(a.verification_state)}`,
            )}
          />
        </div>
      ))}
      <Technical
        title={t.demo.understand.technical}
        items={sorted.map((s) => ({
          label: `set · ${t.demo.review.budget(s.budget)}`,
          value: `${s.set_id} · ${s.scientific_output_sha256}`,
        }))}
        lines={[
          ...new Set(
            sorted.flatMap((s) => [...s.abstention_codes, ...s.limitations]),
          ),
        ]}
      />
    </>
  );
}

function ExampleSet({
  set,
  names,
  profileName,
}: {
  set: AlternativeSet;
  names: (code: string) => string;
  profileName: (code: string) => string;
}) {
  const alternative = set.alternatives[0];
  if (!alternative) return null;
  const others = set.alternatives.length - 1;
  return (
    <div className="example-set">
      <div className="pair">
        <div className="pair-side pair-donor">
          <span className="pair-role">{t.demo.review.donor}</span>
          <span className="pair-name">{names(alternative.donor.org_code)}</span>
          <span className="pair-meta">
            {profileName(alternative.donor.profile_code)} · {t.demo.detect.rank}{" "}
            #{set.donor.inbox_rank ?? "—"}
          </span>
          <span className="pair-sev">
            <SeverityPill value={alternative.donor_severity_before} />
            <Arrow />
            <SeverityPill value={alternative.donor_severity_after} />
          </span>
        </div>
        <div className="pair-link" aria-hidden="true">
          <span className="pair-fraction">
            {percent1(alternative.transfer_fraction)}
          </span>
          <span className="pair-line" />
        </div>
        <div className="pair-side pair-receiver">
          <span className="pair-role">{t.demo.review.receiver}</span>
          <span className="pair-name">
            {names(alternative.receiver.org_code)}
          </span>
          <span className="pair-meta">
            {profileName(alternative.receiver.profile_code)}
          </span>
          <span className="pair-sev">
            <SeverityPill value={alternative.receiver_severity_before} />
            <Arrow />
            <SeverityPill value={alternative.receiver_severity_after} />
          </span>
        </div>
      </div>
      <StatGrid>
        <Stat
          label={t.demo.review.fraction}
          text={percent1(alternative.transfer_fraction)}
          hint={t.demo.review.budget(set.budget)}
        />
        <Stat
          label={t.demo.review.moved}
          value={alternative.transferred_total}
          unit={t.demo.review.over}
        />
        <Stat
          label={t.demo.review.supportTier}
          text={statusLabel(alternative.forecast_support_tier)}
        />
        <Stat
          label={t.demo.review.rangeResult}
          text={statusLabel(alternative.sensitivity_range_result)}
          hint={statusLabel(alternative.receiver_range_evidence)}
        />
      </StatGrid>
      <div className="transfer-pair">
        <TransferChart
          title={`${t.demo.review.donor}: ${names(alternative.donor.org_code)}`}
          before={alternative.baseline_donor_state.cells}
          after={alternative.scenario_donor_state.cells}
          tone="donor"
        />
        <TransferChart
          title={`${t.demo.review.receiver}: ${names(alternative.receiver.org_code)}`}
          before={alternative.baseline_receiver_state.cells}
          after={alternative.scenario_receiver_state.cells}
          tone="receiver"
        />
      </div>
      <p className="chart-note">
        {t.demo.review.before} / {t.demo.review.after} ·{" "}
        {t.demo.review.perHorizon} · {t.demo.review.thresholdMark}:{" "}
        {t.demo.understand.threshold.toLowerCase()}
      </p>
      <div className="verify-row" data-nonclaim="true">
        <span className="verify-item is-ok">{t.demo.review.verified}</span>
        <span className="verify-item is-ok">{t.demo.review.conservation}</span>
        <span className="verify-item is-ok">{t.demo.review.noWorsening}</span>
        {alternative.hierarchy_coherent ? (
          <span className="verify-item is-ok">{t.demo.review.hierarchy}</span>
        ) : null}
        <span className="verify-item is-warn">
          {statusLabel("NOT_PHYSICAL_CAPACITY_VALIDATED")}
        </span>
        <span className="verify-item is-warn">
          {statusLabel("PHYSICAL_FEASIBILITY_UNKNOWN")}
        </span>
      </div>
      {others > 0 ? (
        <p className="chart-note">{t.demo.review.otherAlternatives(others)}</p>
      ) : null}
      <Technical
        title={t.demo.understand.technical}
        items={[
          { label: "Set", value: set.set_id },
          { label: "Alternative", value: alternative.alternative_id },
          { label: "Donor series", value: alternative.donor.series_id },
          { label: "Receiver series", value: alternative.receiver.series_id },
          { label: "Verification", value: alternative.verification_state },
          {
            label: "Fraction certification",
            value: alternative.transfer_fraction_certification,
          },
          {
            label: "Scientific output SHA256",
            value: set.scientific_output_sha256,
          },
          ...Object.entries(set.source_provenance).map(([key, p]) => ({
            label: `${key} · run`,
            value: p.run_id,
          })),
        ]}
        lines={[
          alternative.explanation_text,
          ...alternative.non_claims,
          ...alternative.limitations,
        ]}
      />
    </div>
  );
}
