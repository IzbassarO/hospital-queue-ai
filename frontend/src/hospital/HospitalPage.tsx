/**
 * Hospital mode: one hospital at the published origin. Without an org code the page is the picker; with one it is
 * four blocks — what was forecast, the queue section (who was waiting, with each referral's origin-time estimate,
 * and the verification worklist as a second tab), why that model serves, and what actually happened.
 *
 * Deep link: /hospital/{org_code}. The control-centre map links here too, so a dot on the map and a row in the
 * picker land on the same screen.
 */
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { t } from "../i18n";
import { fmtDate, fmtNumber } from "../lib/format";
import { useWaitingHospital, useWaitingHospitals } from "../api/waiting-list";
import { useReferralEstimatesPublication } from "../api/referral-estimates";
import { useWorklistPublication } from "../api/verification-worklist";
import { ForecastBlock } from "./ForecastBlock";
import { HospitalPicker } from "./HospitalPicker";
import { ModelChoiceBlock } from "./ModelChoiceBlock";
import { QueueSection } from "./QueueSection";
import { ReplayBlock } from "./ReplayBlock";
import { useHospitalProfile } from "./useHospitalProfile";

function Loading() {
  return (
    <div className="scene-state" role="status">
      <span className="pulse" aria-hidden="true" />
      {t.hospital.loading}
    </div>
  );
}

function PickerScreen() {
  const hospitals = useWaitingHospitals();
  const regions = useMemo(() => {
    const byCode = new Map<string, string>();
    for (const h of hospitals.data ?? [])
      byCode.set(h.region_code, h.region_name);
    return [...byCode]
      .map(([code, name]) => ({ code, name }))
      .sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }, [hospitals.data]);
  if (hospitals.isLoading) return <Loading />;
  const origin = hospitals.data?.[0]?.origin ?? null;
  return (
    <>
      <section className="tower-lead">
        <div className="tower-lead-text">
          <h1>{t.hospital.title}</h1>
          <p>{t.hospital.lead(origin ? fmtDate(origin) : "—")}</p>
        </div>
      </section>
      <HospitalPicker hospitals={hospitals.data ?? []} regions={regions} />
    </>
  );
}

function HospitalScreen({ org }: { org: string }) {
  const detail = useWaitingHospital(org);
  // One request for the whole screen: the queue table, the model panel and the calibration view all read it, and
  // it resolves to null when nothing is published, which every consumer treats as "no estimates", not an error.
  const estimates = useReferralEstimatesPublication();
  const published = estimates.data ?? null;
  // the verification worklist is a separate publication and a separate tab; null means the tab simply is not there
  const worklist = useWorklistPublication();
  // Derived, not stored: until the specialist picks one, the profile is the hospital's longest queue. The screen
  // is keyed by org code, so choosing another hospital starts from that hospital's own largest profile.
  const [picked, setPicked] = useState<string | null>(null);
  const profile = picked ?? detail.data?.profiles[0]?.profile_code ?? null;
  const { series, signal, replay, isLoading } = useHospitalProfile(
    org,
    profile,
  );

  if (detail.isLoading) return <Loading />;
  if (detail.error || !detail.data)
    return (
      <div className="hos-empty" role="status">
        <h3>{t.hospital.errors.unknown}</h3>
        <p>{t.hospital.errors.unknownHint}</p>
        <Link className="btn-sm" to="/hospital">
          {t.hospital.errors.back}
        </Link>
      </div>
    );

  const d = detail.data;
  const sparse = d.support_class === "SPARSE";
  return (
    <>
      <section className="tower-lead hos-head">
        <div className="tower-lead-text">
          <p className="hos-kicker">
            {d.region_name} · {t.hospital.header.origin(fmtDate(d.origin))}
          </p>
          <h1>{d.org_name}</h1>
          <p>
            <span className={`hos-support is-${d.support_class.toLowerCase()}`}>
              {t.hospital.header.support[d.support_class]}
            </span>{" "}
            <Link className="hos-change" to="/hospital">
              {t.hospital.pick.change}
            </Link>
          </p>
        </div>
        <dl className="count-chain">
          <div>
            <dd>{fmtNumber(d.waiting_count, 0)}</dd>
            <dt>{t.hospital.header.waiting}</dt>
          </div>
          <div>
            <dd>{fmtNumber(d.profile_count, 0)}</dd>
            <dt>{t.hospital.header.profiles}</dt>
          </div>
          <div className="is-attention">
            <dd>
              {fmtNumber(d.median_days_waited, 0)} {t.hospital.header.days}
            </dd>
            <dt>{t.hospital.header.median}</dt>
          </div>
          <div className="is-high">
            <dd>
              {fmtNumber(d.max_days_waited, 0)} {t.hospital.header.days}
            </dd>
            <dt>{t.hospital.header.longest}</dt>
          </div>
        </dl>
      </section>

      {sparse ? (
        <p className="hos-warn" role="status">
          {t.hospital.header.sparseWarning}
        </p>
      ) : null}

      <section
        className="hos-profile-bar"
        aria-label={t.hospital.profileSelect.label}
      >
        <div className="hos-field">
          <label htmlFor="hos-profile">{t.hospital.profileSelect.label}</label>
          <select
            id="hos-profile"
            value={profile ?? ""}
            onChange={(e) => setPicked(e.target.value)}
          >
            {d.profiles.map((p) => (
              <option key={p.profile_code} value={p.profile_code}>
                {p.profile_name} —{" "}
                {t.hospital.profileSelect.waiting(p.waiting_count)}
              </option>
            ))}
          </select>
        </div>
        <p className="hos-sub-hint">{t.hospital.profileSelect.hint}</p>
      </section>

      {isLoading ? (
        <Loading />
      ) : (
        <ForecastBlock series={series} signal={signal} origin={d.origin} />
      )}
      <QueueSection
        detail={d}
        profile={profile}
        estimates={published}
        worklist={worklist.data ?? null}
      />
      {published?.matches_waiting_list ? (
        <ModelChoiceBlock publication={published} />
      ) : null}
      {isLoading ? null : (
        <ReplayBlock
          key={profile ?? "none"}
          days={replay}
          origin={d.origin}
          estimates={published?.matches_waiting_list ? published : null}
        />
      )}
    </>
  );
}

export function HospitalPage() {
  const { orgCode } = useParams();
  // Keyed by org code: moving to another hospital resets the profile choice and the replay clock.
  return orgCode ? (
    <HospitalScreen key={orgCode} org={orgCode} />
  ) : (
    <PickerScreen />
  );
}
