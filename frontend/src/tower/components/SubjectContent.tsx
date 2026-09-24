/**
 * Everything the specialist needs about one subject (a hospital alert or a patient request): the brief, the AI
 * bubble (empty transport until an endpoint is configured), the attention verdict with reasons, the deterministic
 * facts and explanation, and the decision. Used by the modal and by the notifications page.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { getLang, t } from "../../i18n";
import { fmtDate, fmtNumber } from "../../lib/format";
import { Facts, SeverityPill } from "../../demo/primitives";
import { useAssistantStatus } from "../../api/specialist";
import { askAssistant } from "../ai/assistant";
import { plainExplanation, urgencyText } from "../sim/explain";
import type {
  DecisionAction,
  PatientAction,
  SimState,
} from "../sim/simulation";
import {
  alertVerdict,
  patientVerdict,
  type VerdictReading,
} from "../sim/verdict";
import { daysBetween, flowDecimals } from "../synthetic";
import type { SubjectView } from "../subject";

export function SubjectContent({
  view,
  state,
  onDecideAlert,
  onDecidePatient,
  onClose,
  compact = false,
}: {
  view: SubjectView;
  state: SimState;
  onDecideAlert: (id: string, action: DecisionAction, comment: string) => void;
  onDecidePatient: (id: string, action: PatientAction, comment: string) => void;
  onClose?: () => void;
  compact?: boolean;
}) {
  const { alert, patient } = view;
  const today = state.date;
  const reading: VerdictReading = patient
    ? patientVerdict(patient, alert, view.waiting, today)
    : alert
      ? alertVerdict(alert, view.waiting, today)
      : { verdict: "unclear", reasons: [] };
  const explanation = alert
    ? plainExplanation(alert, view.waiting, today)
    : null;
  const urgency = urgencyText(
    patient ? patient.urgency : (explanation?.urgency ?? "planned"),
  );
  const decided = patient ? patient.decision : alert?.decision;
  const canDecide = patient
    ? patient.status === "request" || patient.status === "waiting"
    : alert
      ? !alert.decision && alert.phase !== "not_confirmed"
      : false;
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState(false);

  const facts = alert
    ? [
        {
          label: t.control.alerts.facts.forecast,
          value:
            alert.central === null
              ? "—"
              : fmtNumber(alert.central, flowDecimals(alert.central)),
          hint: t.control.alerts.facts.perDay,
        },
        {
          label: t.control.alerts.facts.threshold,
          value:
            alert.threshold === null
              ? "—"
              : fmtNumber(alert.threshold, flowDecimals(alert.threshold)),
          hint: t.control.alerts.facts.perDay,
        },
        {
          label: t.control.alerts.facts.interval,
          value:
            alert.lower !== null && alert.upper !== null
              ? `${fmtNumber(alert.lower, flowDecimals(alert.lower))} – ${fmtNumber(alert.upper, flowDecimals(alert.upper))}`
              : t.tower.noInterval.split(".")[0],
          hint: alert.coverage ?? undefined,
        },
        {
          label: t.control.alerts.facts.support,
          value: t.tower.status[alert.support] ?? alert.support,
        },
        {
          label: t.control.alerts.facts.crossing,
          value: alert.crossing
            ? t.control.alerts.whenRelative(
                fmtDate(alert.crossing),
                daysBetween(today, alert.crossing),
              )
            : "—",
        },
        ...(alert.observed !== null
          ? [
              {
                label: t.control.alerts.facts.observed,
                value: fmtNumber(alert.observed, flowDecimals(alert.observed)),
                hint: t.control.alerts.facts.perDay,
              },
            ]
          : []),
        {
          label: t.control.alerts.facts.queue,
          value: t.control.alerts.waiting(view.waiting),
        },
        ...(alert.medianWait !== null
          ? [
              {
                label: t.control.alerts.facts.medianWait,
                value: t.control.queue.days(Math.round(alert.medianWait)),
                hint: t.control.alerts.facts.medianWaitHint,
              },
            ]
          : []),
        ...(alert.queueNow !== null
          ? [
              {
                label: t.control.alerts.facts.queueNow,
                value: fmtNumber(alert.queueNow, 0),
                hint: t.control.alerts.facts.queueNowHint,
              },
            ]
          : []),
      ]
    : [];
  const patientFacts = patient
    ? [
        {
          label: t.control.patientDecision.facts.hospital,
          value: view.hospital,
          hint: `${view.profile} · ${view.region}`,
        },
        {
          label: t.control.patientDecision.facts.referred,
          value: fmtDate(patient.referralDate),
        },
        {
          label: t.control.patientDecision.facts.expected,
          value: fmtDate(patient.predictedDate),
        },
        {
          label: t.control.patientDecision.facts.wait,
          value: t.control.queue.days(patient.predictedWait),
        },
        {
          label: t.control.patientDecision.facts.urgency,
          value: urgency.label,
          hint: urgency.hint,
        },
        ...(alert
          ? [
              {
                label: t.control.patientDecision.facts.pressure,
                value: t.control.alerts.phase[alert.phase],
                hint: t.control.alerts.forecastVs(
                  alert.central === null
                    ? "—"
                    : fmtNumber(alert.central, flowDecimals(alert.central)),
                  alert.threshold === null
                    ? "—"
                    : fmtNumber(alert.threshold, flowDecimals(alert.threshold)),
                ),
              },
            ]
          : []),
      ]
    : [];

  const decide = (action: DecisionAction | PatientAction) => {
    if (patient)
      onDecidePatient(patient.id, action as PatientAction, comment.trim());
    else if (alert)
      onDecideAlert(alert.id, action as DecisionAction, comment.trim());
    setSaved(true);
  };

  return (
    <div className={`subject ${compact ? "is-compact" : ""}`}>
      <header className="subject-head">
        <div className="subject-head-text">
          <div className="subject-tags">
            {alert ? <SeverityPill value={alert.severity} /> : null}
            <span
              className={`alert-urgency is-${patient ? patient.urgency : (explanation?.urgency ?? "planned")}`}
            >
              {urgency.label}
            </span>
            {alert ? (
              <span className={`alert-phase phase-${alert.phase}`}>
                {alert.decision
                  ? t.control.alerts.decided(
                      t.control.decision.actions[alert.decision.action].label,
                    )
                  : t.control.alerts.phase[alert.phase]}
              </span>
            ) : null}
          </div>
          <h2 className="subject-title">
            {patient
              ? `${t.control.patientDecision.title} ${patient.id}`
              : view.hospital}
          </h2>
          <p className="subject-meta">
            {patient
              ? `${view.hospital} · ${view.profile} · ${view.region}`
              : `${view.profile} · ${view.region}`}
          </p>
          {patient ? (
            <p className="subject-when">
              {t.control.patientDecision.facts.expected}:{" "}
              <strong>{fmtDate(patient.predictedDate)}</strong>
              {" · "}
              {t.control.queue.status[patient.status]}
            </p>
          ) : alert?.crossing ? (
            <p className="subject-when">
              {t.control.alerts.whenRelative(
                fmtDate(alert.crossing),
                daysBetween(today, alert.crossing),
              )}
            </p>
          ) : null}
        </div>
        <div
          className={`verdict-medal is-${reading.verdict}`}
          data-nonclaim="true"
          aria-label={t.control.verdict.title}
        >
          <span className="verdict-medal-q">{t.control.verdict.short}</span>
          <strong>{t.control.verdict[reading.verdict]}</strong>
        </div>
      </header>

      <Assistant
        view={view}
        explanation={explanation?.paragraphs ?? []}
        facts={facts.map((f) => `${f.label}: ${f.value}`)}
      />

      <section
        className={`verdict subject-section is-${reading.verdict}`}
        data-nonclaim="true"
        aria-label={t.control.verdict.title}
      >
        <div className="verdict-head">
          <span className="verdict-q">{t.control.verdict.title}</span>
          <span className="verdict-answer">
            {t.control.verdict[reading.verdict]}
          </span>
        </div>
        <p className="verdict-lead">
          {t.control.verdict[`${reading.verdict}Lead` as const]}
        </p>
        <ol className="verdict-reasons">
          {reading.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ol>
        <p className="verdict-note">{t.control.verdict.note}</p>
      </section>

      <section
        className="subject-factbox subject-section"
        aria-label={t.control.alerts.facts.title}
      >
        <h3 className="focus-sub">{t.control.alerts.facts.title}</h3>
        <Facts
          rows={patient ? patientFacts : facts}
          className={compact || patient ? "" : "facts-columns"}
        />
      </section>

      {explanation ? (
        <section
          className="plain subject-section"
          data-nonclaim="true"
          aria-label={t.control.alerts.plainTitle}
        >
          <h3 className="plain-title">{t.control.alerts.plainTitle}</h3>
          {explanation.paragraphs.map((p) => (
            <p key={p}>{p}</p>
          ))}
          <p className="plain-note">{t.control.alerts.plainNote}</p>
        </section>
      ) : null}

      <footer className="subject-actions">
        {saved || decided ? (
          <p className="subject-recorded" role="status">
            {t.control.decision.recorded}
            {decided
              ? `: ${patient ? t.control.patientDecision.actions[(decided as { action: PatientAction }).action].label : t.control.decision.actions[(decided as { action: DecisionAction }).action].label}`
              : ""}
          </p>
        ) : canDecide ? (
          <>
            <label className="decision-comment">
              <span>{t.control.decision.comment}</span>
              <textarea
                rows={compact ? 1 : 2}
                value={comment}
                placeholder={t.control.decision.commentPlaceholder}
                onChange={(e) => setComment(e.target.value)}
              />
            </label>
            <div className="decision-actions">
              <button
                type="button"
                className="btn-accent"
                onClick={() => decide(patient ? "confirm" : "accept")}
              >
                {patient
                  ? t.control.patientDecision.actions.confirm.label
                  : t.control.decision.actions.accept.label}
              </button>
              <button
                type="button"
                className="btn-danger"
                onClick={() => decide("decline")}
              >
                {patient
                  ? t.control.patientDecision.actions.decline.label
                  : t.control.decision.actions.decline.label}
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => decide(patient ? "postpone" : "clarify")}
              >
                {patient
                  ? t.control.patientDecision.actions.postpone.label
                  : t.control.decision.actions.clarify.label}
              </button>
              {onClose ? (
                <button type="button" className="btn-link" onClick={onClose}>
                  {t.control.decision.cancel}
                </button>
              ) : null}
            </div>
            <p className="decision-hint">
              {patient
                ? t.control.patientDecision.actions[
                    comment ? "confirm" : "confirm"
                  ].body
                : t.control.decision.lead}
            </p>
          </>
        ) : null}
        {alert ? (
          <Link
            to={`/demo/detect?signal=${encodeURIComponent(alert.id)}`}
            className="alert-link"
            onClick={onClose}
          >
            {t.control.alerts.openStory}
          </Link>
        ) : null}
      </footer>
    </div>
  );
}

function Assistant({
  view,
  explanation,
  facts,
}: {
  view: SubjectView;
  explanation: string[];
  facts: string[];
}) {
  const [question, setQuestion] = useState("");
  const [thread, setThread] = useState<{ role: "you" | "ai"; text: string }[]>(
    [],
  );
  const [busy, setBusy] = useState(false);
  const status = useAssistantStatus();
  const connected = status.data?.configured ?? false;
  const send = async () => {
    const q = question.trim();
    if (!q || busy) return;
    setThread((th) => [...th, { role: "you", text: q }]);
    setQuestion("");
    setBusy(true);
    try {
      const reply = await askAssistant(
        {
          lang: getLang(),
          question: q,
          facts,
          explanation,
          subject: {
            kind: view.subject.kind,
            id: view.subject.id,
            hospital: view.hospital,
          },
        },
        t.control.assistant.stub,
      );
      setThread((th) => [...th, { role: "ai", text: reply.text }]);
    } catch {
      setThread((th) => [
        ...th,
        { role: "ai", text: t.control.assistant.error },
      ]);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      className="assistant subject-section"
      aria-label={t.control.assistant.title}
    >
      <div className="assistant-head">
        <span className="assistant-title">{t.control.assistant.title}</span>
        <span className={`assistant-badge ${connected ? "is-on" : ""}`}>
          {connected
            ? t.control.assistant.badgeReady
            : t.control.assistant.badge}
        </span>
      </div>
      <div className="bubble bubble-ai">
        <p>{connected ? t.control.assistant.lead : t.control.assistant.stub}</p>
        {!connected ? (
          <p className="bubble-note">{t.control.assistant.leadOff}</p>
        ) : null}
      </div>
      {thread.map((m, i) => (
        <div
          key={i}
          className={`bubble ${m.role === "you" ? "bubble-you" : "bubble-ai"}`}
        >
          <span className="bubble-role">
            {m.role === "you"
              ? t.control.assistant.you
              : t.control.assistant.title}
          </span>
          <p>{m.text}</p>
        </div>
      ))}
      <form
        className="assistant-form"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          type="text"
          value={question}
          placeholder={t.control.assistant.placeholder}
          aria-label={t.control.assistant.placeholder}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button
          type="submit"
          className="btn-ghost btn-sm"
          disabled={busy || !question.trim()}
        >
          {busy ? t.control.assistant.sending : t.control.assistant.send}
        </button>
      </form>
      <p className="assistant-disclaimer">{t.control.assistant.disclaimer}</p>
    </section>
  );
}
