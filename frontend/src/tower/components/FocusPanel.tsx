/** The hospital in focus: what is happening there in one paragraph, its forecast, its queue and its neighbours. */
import { useForecasts } from "../../api/operational";
import { t } from "../../i18n";
import { fmtDate, fmtNumber } from "../../lib/format";
import { SeverityPill } from "../../demo/primitives";
import type { SimState } from "../sim/simulation";
import { daysBetween, flowDecimals } from "../synthetic";
import { openSubject } from "../ui";
import type { TowerHospital } from "../useTowerData";
import { Sparkline } from "./Sparkline";

export function FocusPanel({
  hospital,
  neighbours,
  state,
  origin,
  profileName,
  onFocus,
  onClear,
}: {
  hospital: TowerHospital;
  neighbours: TowerHospital[];
  state: SimState;
  origin: string;
  profileName: (code: string) => string;
  onFocus: (org: string) => void;
  onClear: () => void;
}) {
  const top = hospital.signals[0];
  const forecast = useForecasts({
    origin,
    org: top?.org ?? undefined,
    profile: top?.profile ?? undefined,
    target: top?.target,
    level: "hospital",
    limit: 500,
    offset: 0,
  });
  const series = top
    ? forecast.data?.series.find((s) => s.seriesId === top.seriesId)
    : undefined;
  const own = state.patients.filter((p) => p.org === hospital.org);
  const waiting = own.filter(
    (p) => p.status !== "admitted" && p.status !== "declined",
  ).length;
  const requests = own.filter((p) => p.status === "request").length;
  const simAlert = state.alerts.find((a) => a.org === hospital.org);
  const story: string[] = [];
  if (top?.rawCrossing)
    story.push(
      t.control.focus.storyAlert(
        profileName(top.profile ?? ""),
        t.control.alerts.whenRelative(
          fmtDate(top.rawCrossing),
          daysBetween(state.date, top.rawCrossing),
        ),
      ),
    );
  else story.push(t.control.focus.storyQuiet);
  if (simAlert) story.push(t.control.focus.storyPhase[simAlert.phase]);
  story.push(t.control.focus.queueLine(waiting, requests));
  return (
    <section className="focus" aria-label={t.control.focus.title}>
      <header className="block-head block-head-row">
        <div>
          <p className="focus-kicker">{t.control.focus.title}</p>
          <h2>{hospital.name}</h2>
          <p>{hospital.regionName}</p>
        </div>
        <div className="focus-head-actions">
          {simAlert ? (
            <button
              type="button"
              className="btn-accent btn-sm"
              onClick={() => openSubject({ kind: "alert", id: simAlert.id })}
            >
              {t.control.focus.openAlert}
            </button>
          ) : null}
          <button type="button" className="btn-ghost btn-sm" onClick={onClear}>
            {t.control.focus.clear}
          </button>
        </div>
      </header>
      <div className="focus-grid">
        <div>
          <h3 className="focus-sub">{t.control.focus.story}</h3>
          <p className="prose focus-story">{story.join(" ")}</p>
          <h3 className="focus-sub">{t.control.focus.signals}</h3>
          {hospital.signals.length === 0 ? (
            <p className="empty">{t.control.map.noSignal}</p>
          ) : (
            <ul className="focus-signals">
              {hospital.signals.slice(0, 5).map((s) => (
                <li key={s.id}>
                  <SeverityPill value={s.severity} />
                  <span className="focus-signal-profile">
                    {profileName(s.profile ?? "")}
                  </span>
                  <span className="focus-signal-when">
                    {s.rawCrossing ? fmtDate(s.rawCrossing) : "—"} ·{" "}
                    {s.rawForecast == null
                      ? "—"
                      : fmtNumber(
                          s.rawForecast,
                          flowDecimals(s.rawForecast),
                        )}{" "}
                    /{" "}
                    {s.rawThreshold == null
                      ? "—"
                      : fmtNumber(s.rawThreshold, flowDecimals(s.rawThreshold))}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <h3 className="focus-sub">{t.control.focus.patients}</h3>
          {own.length === 0 ? (
            <p className="empty">{t.control.queue.empty}</p>
          ) : (
            <ul className="focus-queue">
              {own.slice(0, 6).map((p) => (
                <li key={p.id} className={`status-${p.status}`}>
                  <button
                    type="button"
                    className="cell-link mono"
                    onClick={() => openSubject({ kind: "patient", id: p.id })}
                  >
                    {p.id}
                  </button>
                  <span>{profileName(p.profile)}</span>
                  <strong>{fmtDate(p.admittedDate ?? p.predictedDate)}</strong>
                  <span className={`queue-status is-${p.status}`}>
                    {t.control.queue.status[p.status]}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          {top ? (
            <>
              <h3 className="focus-sub">
                {t.control.focus.forecastTitle} ·{" "}
                {profileName(top.profile ?? "")}
              </h3>
              {series ? (
                <Sparkline
                  points={series.points
                    .filter((p) => p.central !== null)
                    .map((p) => ({
                      date: p.date,
                      central: p.central as number,
                      interval: p.interval,
                    }))}
                  threshold={top.rawThreshold ?? null}
                  crossing={top.rawCrossing ?? null}
                />
              ) : forecast.isPending ? (
                <p className="empty">{t.common.loading}</p>
              ) : (
                <p className="empty">{t.control.focus.noForecast}</p>
              )}
            </>
          ) : null}
          {neighbours.length ? (
            <>
              <h3 className="focus-sub">{t.control.focus.neighbours}</h3>
              <ul className="focus-neighbours">
                {neighbours.slice(0, 8).map((h) => (
                  <li key={h.org}>
                    <button
                      type="button"
                      className="cell-link"
                      onClick={() => onFocus(h.org)}
                    >
                      {h.name}
                    </button>
                    {h.severity ? <SeverityPill value={h.severity} /> : null}
                  </li>
                ))}
                {neighbours.length > 8 ? (
                  <li className="muted">+{neighbours.length - 8}</li>
                ) : null}
              </ul>
            </>
          ) : null}
        </div>
      </div>
    </section>
  );
}
