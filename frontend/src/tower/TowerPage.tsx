/**
 * The main page: the big picture. Map, the day unfolding in the feed, how many people wait, and the top of the
 * specialist's inbox. Long listings live on their own pages. Real: published overview, signals, forecasts,
 * registry (hospital positions are derived from it). Synthetic and labelled, only while the layer is on: the
 * queue and the fourteen-day flow; with the layer off the page shows the published origin state instead.
 * One vocabulary for every counter: published signals → attention queue (after the materiality floor) → high.
 */
import { useMemo, useState } from "react";
import { t } from "../i18n";
import { fmtDate, fmtNumber } from "../lib/format";
import { NonClaims } from "../demo/primitives";
import { FactStrip } from "./components/FactStrip";
import { Feed } from "./components/Feed";
import { FocusPanel } from "./components/FocusPanel";
import { KazMap } from "./components/KazMap";
import { PriorityList } from "./components/PriorityList";
import { RegistryNote } from "./components/RegistryNote";
import { SimulationBar } from "./components/SimulationBar";
import { SyntheticOffNote } from "./components/SyntheticState";
import { TowerError } from "./components/TowerError";
import { WaitingStrip } from "./components/WaitingStrip";
import { scenarioDef, SYNTHETIC_ENABLED } from "./synthetic";
import { openSubject } from "./ui";
import { useNames, useTowerData, useTowerSimulation } from "./useTowerModel";
import type { TowerModel } from "./useTowerData";

export function TowerPage() {
  const { model, isPending, error, refetch } = useTowerData();
  if (!model && error) return <TowerError error={error} onRetry={refetch} />;
  if (!model)
    return (
      <div className="scene-state" role="status" aria-live="polite">
        <span className="pulse" aria-hidden="true" />
        {isPending ? t.control.loading : t.tower.unavailable}
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
  const c = model.counts;
  return (
    <>
      <section className="tower-lead" data-tour="lead">
        <h1>{t.control.title}</h1>
        <p>
          {t.control.lead(
            fmtNumber(c.total, 0),
            fmtNumber(c.hospitals, 0),
            fmtNumber(c.attention, 0),
            fmtNumber(c.highMaterial, 0),
            fmtNumber(c.lowVolume, 0),
            fmtDate(model.origin),
          )}
          {c.complete ? "" : ` ${t.control.leadIncomplete}`}
        </p>
        <dl className="count-chain" aria-label={t.control.title}>
          <div>
            <dd>{fmtNumber(c.total, 0)}</dd>
            <dt>{t.control.chain.published}</dt>
          </div>
          <div className="is-attention">
            <dd>{fmtNumber(c.attention, 0)}</dd>
            <dt>{t.control.chain.attention}</dt>
          </div>
          <div className="is-high">
            <dd>{fmtNumber(c.highMaterial, 0)}</dd>
            <dt>{t.control.chain.high}</dt>
          </div>
          <div className="is-muted">
            <dd>{fmtNumber(c.lowVolume, 0)}</dd>
            <dt>{t.control.chain.lowVolume}</dt>
          </div>
        </dl>
      </section>
      <div data-tour="waiting" className="waiting-row">
        <WaitingStrip state={state} />
        <FactStrip regionName={model.regionName} />
      </div>
      {SYNTHETIC_ENABLED ? (
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
      ) : (
        <SyntheticOffNote origin={model.origin} />
      )}
      <div className="tower-grid">
        <section
          className="map-block"
          aria-label={t.control.map.title}
          data-tour="map"
        >
          <KazMap
            hospitals={hospitals}
            regions={model.regionByCode}
            lowVolumeTotal={c.lowVolume}
            profileName={model.profileName}
            focus={focus}
            pulse={pulse}
            outageRegion={outage}
            onFocus={onFocus}
          />
          <p className="map-note">
            {t.control.map.hospitals(fmtNumber(c.hospitals, 0))} ·{" "}
            {t.control.map.hint} {t.control.map.borders} <RegistryNote />
          </p>
        </section>
        <Feed
          state={state}
          attention={c.attention}
          limit={40}
          onOpen={openSubject}
          onFocus={onFocus}
        />
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
