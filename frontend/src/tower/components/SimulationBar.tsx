/** Day clock, scenario choice, controls and counters of the fourteen-day simulation. */
import { t } from "../../i18n";
import { fmtDate, fmtNumber } from "../../lib/format";
import { GlyphPause, GlyphPlay, GlyphReplay } from "../../demo/glyphs";
import type { ScenarioId } from "../synthetic";
import { clockLabel, SIM_DAYS, type SimState } from "../sim/simulation";
import { pendingTasks } from "../sim/tasks";

const SCENARIOS: ScenarioId[] = ["baseline", "surge", "season", "outage"];

export function SimulationBar({
  state,
  speed,
  onSpeed,
  onPlay,
  onPause,
  onStep,
  onReset,
  onScenario,
}: {
  state: SimState;
  speed: number;
  onSpeed: (s: number) => void;
  onPlay: () => void;
  onPause: () => void;
  onStep: () => void;
  onReset: () => void;
  onScenario: (s: ScenarioId) => void;
}) {
  const pending = pendingTasks(state).length;
  const scenario = t.control.sim.scenarios[state.scenario];
  return (
    <section className="simbar" aria-label={t.control.sim.title}>
      <div className="sim-clock">
        <span className="sim-day" role="status" aria-live="polite">
          {t.control.sim.day(state.day)}
        </span>
        <span className="sim-date">
          {fmtDate(state.date)} · {t.control.sim.dayOf(state.day, SIM_DAYS)}
          {state.day > 0 ? ` · ${clockLabel(state.clock)}` : ""}
          {state.playing ? ` · ${t.control.feed.live}` : ""}
        </span>
        <ol className="sim-track" aria-hidden="true">
          {Array.from({ length: SIM_DAYS }, (_, i) => (
            <li
              key={i}
              className={
                i < state.day ? "is-past" : i === state.day - 1 ? "is-now" : ""
              }
            />
          ))}
        </ol>
      </div>
      <div className="sim-controls" data-tour="play">
        {state.finished ? (
          <button type="button" className="btn-lime" onClick={onReset}>
            <GlyphReplay /> {t.control.sim.reset}
          </button>
        ) : state.playing ? (
          <button
            type="button"
            className="btn-lime"
            onClick={onPause}
            aria-pressed="true"
          >
            <GlyphPause /> {t.control.sim.pause}
          </button>
        ) : (
          <button type="button" className="btn-lime" onClick={onPlay}>
            <GlyphPlay /> {t.control.sim.play}
          </button>
        )}
        <button
          type="button"
          className="btn-ghost"
          onClick={onStep}
          disabled={state.finished}
        >
          {t.control.sim.step}
        </button>
        {state.day > 0 && !state.finished ? (
          <button type="button" className="btn-ghost" onClick={onReset}>
            {t.control.sim.reset}
          </button>
        ) : null}
        <div
          className="sim-speed"
          role="group"
          aria-label={t.control.sim.speed}
        >
          {[1, 2, 4].map((s) => (
            <button
              key={s}
              type="button"
              className={`chip ${speed === s ? "is-active" : ""}`}
              aria-pressed={speed === s}
              onClick={() => onSpeed(s)}
            >
              ×{s}
            </button>
          ))}
        </div>
      </div>
      <div className="sim-scenario">
        <div
          className="sim-chips"
          role="group"
          aria-label={t.control.sim.scenarioLabel}
        >
          {SCENARIOS.map((id) => (
            <button
              key={id}
              type="button"
              className={`chip ${state.scenario === id ? "is-active" : ""}`}
              aria-pressed={state.scenario === id}
              onClick={() => onScenario(id)}
            >
              {t.control.sim.scenarios[id].label}
            </button>
          ))}
        </div>
        <p className="sim-scenario-body">{scenario.body}</p>
      </div>
      {state.pausedForDecision ? (
        <p className="sim-note" role="status">
          {t.control.sim.pausedForDecision}
        </p>
      ) : state.finished ? (
        <p className="sim-note" role="status">
          {t.control.sim.finished}
        </p>
      ) : null}
      <dl className="sim-counters">
        <div>
          <dd>
            {state.stats.arrivalsToday === null
              ? "—"
              : fmtNumber(state.stats.arrivalsToday, 0)}
          </dd>
          <dt>{t.control.sim.counters.arrivalsToday}</dt>
        </div>
        <div>
          <dd>{fmtNumber(state.stats.admitted, 0)}</dd>
          <dt>{t.control.sim.counters.admitted}</dt>
        </div>
        <div className={pending ? "is-attention" : ""}>
          <dd>{fmtNumber(pending, 0)}</dd>
          <dt>{t.control.sim.counters.pending}</dt>
        </div>
        <div>
          <dd>{fmtNumber(state.stats.confirmed, 0)}</dd>
          <dt>{t.control.sim.counters.confirmed}</dt>
        </div>
        {state.scenario === "outage" ? (
          <div>
            <dd>{fmtNumber(state.stats.unverified, 0)}</dd>
            <dt>{t.control.sim.counters.unverified}</dt>
          </div>
        ) : null}
      </dl>
    </section>
  );
}
