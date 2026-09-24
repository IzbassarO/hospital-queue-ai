/**
 * Mounted by every layout: the bell with the open-task count, the language switch, the task drawer and the
 * subject dialog. Reads the shared simulation store, so it works on any page once the simulation exists.
 */
import { useCallback } from "react";
import { LANGS, setLang, t, useLang, type Lang } from "../i18n";
import { GlyphBell } from "../demo/glyphs";
import { Explorer } from "./components/Explorer";
import { resolveSubject } from "./subject";
import { SubjectDialog } from "./components/SubjectDialog";
import { pendingTasks } from "./sim/tasks";
import { dispatchSim, useSimState, useSimText } from "./sim/useSimulation";
import { persistDecision, useNames, useTowerData } from "./useTowerModel";
import { closeSubject, toggleExplorer, useUi } from "./ui";

export function LanguageSwitch() {
  const lang = useLang();
  return (
    <div
      className="lang-switch"
      role="group"
      aria-label={t.control.nav.language}
    >
      {LANGS.map((code: Lang) => (
        <button
          key={code}
          type="button"
          className={`lang-btn ${lang === code ? "is-active" : ""}`}
          aria-pressed={lang === code}
          lang={code}
          onClick={() => setLang(code)}
        >
          {code === "ru" ? "RU" : "KZ"}
        </button>
      ))}
    </div>
  );
}

export function TaskBell() {
  const state = useSimState();
  const ui = useUi();
  const count = state ? pendingTasks(state).length : 0;
  return (
    <button
      type="button"
      className={`bell ${ui.explorerOpen ? "is-open" : ""} ${count ? "has-tasks" : ""}`}
      aria-label={t.control.nav.tasks}
      title={t.control.nav.tasksHint}
      aria-pressed={ui.explorerOpen}
      onClick={toggleExplorer}
    >
      <GlyphBell size={18} />
      {count ? <span className="bell-count">{count}</span> : null}
    </button>
  );
}

export function TaskHost() {
  const state = useSimState();
  const ui = useUi();
  const { model } = useTowerData();
  const names = useNames(model);
  const text = useSimText(names.region);
  const day = state?.day ?? 0;
  const runId = state?.runId ?? "";
  const onDecideAlert = useCallback(
    (
      alertId: string,
      action: "accept" | "decline" | "clarify",
      comment: string,
    ) => {
      dispatchSim({ type: "decide", alertId, action, comment, text });
      if (model)
        persistDecision(model, runId, "alert", alertId, action, comment, day);
    },
    [text, model, runId, day],
  );
  const onDecidePatient = useCallback(
    (
      patientId: string,
      action: "confirm" | "decline" | "postpone",
      comment: string,
    ) => {
      dispatchSim({ type: "patientDecide", patientId, action, comment, text });
      if (model)
        persistDecision(
          model,
          runId,
          "patient",
          patientId,
          action,
          comment,
          day,
        );
    },
    [text, model, runId, day],
  );
  const view =
    ui.subject && state ? resolveSubject(ui.subject, state, names) : null;
  return (
    <>
      <Explorer state={state} open={ui.explorerOpen} names={names} />
      {view && state ? (
        <SubjectDialog
          key={`${view.subject.kind}:${view.subject.id}`}
          view={view}
          state={state}
          onDecideAlert={onDecideAlert}
          onDecidePatient={onDecidePatient}
          onClose={closeSubject}
        />
      ) : null}
    </>
  );
}
