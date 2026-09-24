/**
 * The main page: the big picture. Map, the day unfolding in the feed, how many people wait, and the top of the
 * specialist's inbox. Long listings live on their own pages. Real: published overview, signals, forecasts,
 * registry. Synthetic and labelled: hospital positions, the queue, the fourteen-day flow.
 */
import { useMemo, useState } from "react";
import { ApiError } from "../api/client";
import { t } from "../i18n";
import { fmtDate, fmtNumber } from "../lib/format";
import { NonClaims } from "../demo/primitives";
import { Feed } from "./components/Feed";
import { FocusPanel } from "./components/FocusPanel";
import { KazMap } from "./components/KazMap";
import { PriorityList } from "./components/PriorityList";
import { SimulationBar } from "./components/SimulationBar";
import { WaitingStrip } from "./components/WaitingStrip";
import { scenarioDef } from "./synthetic";
import { openSubject } from "./ui";
import { useNames, useTowerData, useTowerSimulation } from "./useTowerModel";
import type { TowerModel } from "./useTowerData";

export function TowerPage() {
  const { model, isPending, error } = useTowerData();
  if (isPending && !model)
    return (
      <div className="scene-state" role="status" aria-live="polite">
        <span className="pulse" aria-hidden="true" />
        {t.control.loading}
      </div>
    );
  if (!model)
    return (
      <div className="scene-state" role="alert">
        <h2>{t.errors.title}</h2>
        <p>
          {error instanceof ApiError && error.status === 404
            ? t.control.unavailable
            : (error?.message ?? t.tower.unavailable)}
        </p>
      </div>
    );
  return <Board model={model} />;
}

function Board({ model }: { model: TowerModel }) {
  const [focus, setFocus] = useState<string | null>(null);
  const [speed, setSpeed] = useState(1);
  const sim = useTowerSimulation(model, speed);
  const { state } = sim;
  const names = useNames(model);
  const pulse = useMemo(
    () =>
      new Set(
        state.events
          .filter((e) => e.day === state.day && e.org && e.kind !== "arrivals")
          .map((e) => e.org as string),
      ),
    [state.events, state.day],
  );
  const hospitals = useMemo(
    () =>
      model.hospitals.map((h) => {
        const escalated = state.alerts.some(
          (a) => a.org === h.org && a.phase === "escalated",
        );
        return escalated && h.severity !== "HIGH"
          ? { ...h, severity: "HIGH" as const }
          : h;
      }),
    [model.hospitals, state.alerts],
  );
  const outage = scenarioDef(state.scenario, model.outageRegion).outageRegion;
  const focused = focus ? (model.byOrg.get(focus) ?? null) : null;
  const onFocus = (org: string | null) => {
    setFocus(org);
    if (org)
      window.setTimeout(
        () =>
          document
            .getElementById("focus")
            ?.scrollIntoView({ behavior: "smooth", block: "start" }),
        30,
      );
  };
  return (
    <>
      <section className="tower-lead" data-tour="lead">
        <h1>{t.control.title}</h1>
        <p>
          {t.control.lead(
            model.counts.total,
            fmtNumber(model.counts.hospitals, 0),
            fmtNumber(model.counts.high, 0),
            fmtDate(model.origin),
          )}
        </p>
      </section>
      <div data-tour="waiting">
        <WaitingStrip state={state} />
      </div>
      <SimulationBar
        state={state}
        speed={speed}
        onSpeed={setSpeed}
        onPlay={sim.play}
        onPause={sim.pause}
        onStep={sim.step}
        onReset={sim.reset}
        onScenario={sim.setScenario}
      />
      <div className="tower-grid">
        <section
          className="map-block"
          aria-label={t.control.map.title}
          data-tour="map"
        >
          <KazMap
            hospitals={hospitals}
            regions={model.regionByCode}
            profileName={model.profileName}
            focus={focus}
            pulse={pulse}
            outageRegion={outage}
            onFocus={onFocus}
          />
          <p className="map-note">
            {t.control.map.hospitals(fmtNumber(model.counts.hospitals, 0))} ·{" "}
            {t.control.map.hint} {t.control.map.borders}
          </p>
        </section>
        <Feed state={state} limit={40} onOpen={openSubject} onFocus={onFocus} />
      </div>
      {focused ? (
        <div id="focus" className="focus-anchor">
          <FocusPanel
            hospital={focused}
            neighbours={model.hospitals.filter(
              (h) => h.anchor === focused.anchor && h.org !== focused.org,
            )}
            state={state}
            origin={model.origin}
            profileName={model.profileName}
            onFocus={onFocus}
            onClear={() => setFocus(null)}
          />
        </div>
      ) : null}
      <PriorityList state={state} names={names} />
      <NonClaims
        title={t.control.nonclaims.title}
        items={t.control.nonclaims.items}
      />
    </>
  );
}
