import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  useCreateDecision,
  useDecisions,
  useRecommendations,
} from "../../api/queries";
import type {
  Alternative,
  DecisionAction,
  Recommendations as RecommendationsData,
} from "../../api/types";
import { type Column, DataTable } from "../../components/DataTable";
import { ErrorState } from "../../components/ErrorState";
import { IconCheck, IconUser } from "../../components/icons";
import { Section } from "../../components/PageHeader";
import { BlockSkeleton, TableSkeleton } from "../../components/Skeleton";
import { t } from "../../i18n";
import { fmtDateTime, fmtDays, fmtIndex, fmtPercent } from "../../lib/format";
import { hospitalPath } from "../../lib/paths";

const ACTIONS: DecisionAction[] = ["confirm", "reject", "defer"];
const ACTOR_KEY = "hqai.decision.actor";

function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === "function")
    return `ui-${crypto.randomUUID()}`;
  // crypto.randomUUID needs a secure context (https or localhost); fall back to random bytes
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return `ui-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

function rememberedActor(): string {
  try {
    return window.localStorage.getItem(ACTOR_KEY) ?? "";
  } catch {
    return "";
  }
}

function HumanDecides() {
  return (
    <p className="flex items-center gap-2 rounded-md border border-accent-600/30 bg-accent-50 px-3 py-2 font-medium text-accent-800">
      <IconUser size={18} />
      {t.recommendations.humanDecides}
    </p>
  );
}

export function Recommendations({
  org,
  profile,
}: {
  org: string;
  profile: string;
}) {
  const query = useRecommendations(org, profile);
  const [saved, setSaved] = useState<string | null>(null);

  return (
    <Section title={t.recommendations.title} id="recommendations">
      <HumanDecides />
      {saved ? (
        <p
          role="status"
          className="flex items-center gap-2 font-medium text-normal-fg"
        >
          <IconCheck size={18} />
          {saved}
        </p>
      ) : null}
      {query.isPending ? (
        <BlockSkeleton height="h-40" />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <RecommendationList data={query.data} onSaved={setSaved} />
      )}
      <DecisionHistory org={org} profile={profile} />
    </Section>
  );
}

function RecommendationList({
  data,
  onSaved,
}: {
  data: RecommendationsData;
  onSaved: (message: string) => void;
}) {
  const rule = t.recommendations.rule(
    Math.round(data.rule.region_top_fraction * 100),
    fmtDays(data.rule.min_wait_delta_days, 0),
  );
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">{rule}</p>
      {data.alternatives.length === 0 ? (
        <div className="card space-y-1 p-4">
          <p className="font-semibold">{t.recommendations.notEligible}</p>
          {data.reason ? <p>{data.reason}</p> : null}
        </div>
      ) : (
        <ol className="space-y-3">
          {data.alternatives.map((alternative, i) => (
            <li key={alternative.recommendation_id}>
              <AlternativeCard
                index={i + 1}
                alternative={alternative}
                context={data}
                onSaved={onSaved}
              />
            </li>
          ))}
        </ol>
      )}
      <p className="text-sm text-muted">{data.disclaimer}</p>
    </div>
  );
}

function Figure({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <div>
      <dt className="text-sm text-muted">{label}</dt>
      <dd
        className={`tabular-nums ${strong ? "text-xl font-semibold" : "text-lg"}`}
      >
        {value}
      </dd>
    </div>
  );
}

function AlternativeCard({
  index,
  alternative: a,
  context,
  onSaved,
}: {
  index: number;
  alternative: Alternative;
  context: RecommendationsData;
  onSaved: (message: string) => void;
}) {
  const [action, setAction] = useState<DecisionAction | null>(null);

  return (
    <article
      className="card space-y-3 p-4"
      aria-labelledby={`${a.recommendation_id}-title`}
    >
      <header className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm text-muted">
            {t.recommendations.alternativeTitle(index)}
          </p>
          <h3
            id={`${a.recommendation_id}-title`}
            className="text-lg font-semibold"
          >
            <Link
              to={hospitalPath(a.org_code, a.profile_code)}
              className="link"
            >
              {a.org_name}
            </Link>
          </h3>
        </div>
        <span className="shrink-0 whitespace-nowrap rounded-full border border-line bg-canvas px-2.5 py-0.5 text-sm font-medium text-muted">
          {t.recommendations.methodBadge}
        </span>
      </header>

      <dl className="grid grid-cols-3 gap-x-6 gap-y-2 xl:grid-cols-6">
        <Figure
          label={t.recommendations.waitCurrent}
          value={fmtDays(a.expected_wait_current)}
        />
        <Figure
          label={t.recommendations.waitAlternative}
          value={fmtDays(a.expected_wait_alternative)}
          strong
        />
        <Figure
          label={t.recommendations.delta}
          value={t.recommendations.deltaValue(fmtDays(a.delta_days))}
          strong
        />
        <Figure
          label={t.recommendations.refusalCurrent}
          value={fmtPercent(a.refusal_rate_current)}
        />
        <Figure
          label={t.recommendations.refusalAlternative}
          value={fmtPercent(a.refusal_rate_alternative)}
        />
        <Figure
          label={t.recommendations.backlog}
          value={t.recommendations.backlogCompare(
            fmtDays(a.backlog_days_current),
            fmtDays(a.backlog_days_alternative),
          )}
        />
      </dl>
      <p className="leading-relaxed">{a.explanation}</p>
      <p className="text-sm text-muted">
        {t.recommendations.loadIndexAlternative}:{" "}
        {fmtIndex(a.load_index_alternative)}
      </p>

      <div
        className="flex flex-wrap gap-2"
        role="group"
        aria-label={t.recommendations.title}
      >
        {ACTIONS.map((candidate) => (
          <button
            key={candidate}
            type="button"
            className={`btn ${action === candidate ? "btn-primary" : ""}`}
            aria-pressed={action === candidate}
            onClick={() =>
              setAction((current) => (current === candidate ? null : candidate))
            }
          >
            {t.recommendations.actions[candidate]}
          </button>
        ))}
      </div>

      {action ? (
        <DecisionForm
          action={action}
          context={context}
          recommendationId={a.recommendation_id}
          alternativeOrgCode={a.org_code}
          onCancel={() => setAction(null)}
          onSaved={() => {
            setAction(null);
            onSaved(
              `${t.recommendations.form.saved}: ${t.decisions.actionPast[action].toLowerCase()} — ${a.org_name}`,
            );
          }}
        />
      ) : null}
    </article>
  );
}

function DecisionForm({
  action,
  context,
  recommendationId,
  alternativeOrgCode,
  onCancel,
  onSaved,
}: {
  action: DecisionAction;
  context: RecommendationsData;
  recommendationId: string;
  alternativeOrgCode: string;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const id = useId();
  const [comment, setComment] = useState("");
  const [actor, setActor] = useState(rememberedActor);
  const [touched, setTouched] = useState(false);
  const mutation = useCreateDecision(context.org_code, context.profile_code);
  const commentRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => commentRef.current?.focus(), []);

  const actorMissing = actor.trim() === "";
  // one key per distinct submission: a double click or a retry after a network error sends the same content with
  // the same key and gets the stored decision back instead of a duplicate; changed content gets a new key
  const submission = useRef<{ signature: string; key: string } | null>(null);
  const idempotencyKeyFor = (signature: string) => {
    if (submission.current?.signature !== signature) {
      submission.current = { signature, key: newIdempotencyKey() };
    }
    return submission.current.key;
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (actorMissing) return;
    try {
      window.localStorage.setItem(ACTOR_KEY, actor.trim());
    } catch {
      // storage unavailable: the actor just is not remembered
    }
    mutation.mutate(
      {
        region_code: context.region_code,
        org_code: context.org_code,
        profile_code: context.profile_code,
        recommendation_id: recommendationId,
        alternative_org_code: alternativeOrgCode,
        idempotency_key: idempotencyKeyFor(
          JSON.stringify([action, comment.trim(), actor.trim()]),
        ),
        action,
        comment: comment.trim() || null,
        actor: actor.trim(),
      },
      { onSuccess: onSaved },
    );
  };

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-md border border-accent-600/40 bg-accent-50/50 p-4"
      noValidate
    >
      <p className="font-semibold">
        {t.recommendations.form.title(t.recommendations.actions[action])}
      </p>
      <div className="grid gap-3 lg:grid-cols-2">
        <div>
          <label
            htmlFor={`${id}-comment`}
            className="mb-1 block text-sm font-medium"
          >
            {t.recommendations.form.comment}
          </label>
          <textarea
            id={`${id}-comment`}
            ref={commentRef}
            className="field min-h-20"
            maxLength={4000}
            value={comment}
            placeholder={t.recommendations.form.commentPlaceholder}
            onChange={(e) => setComment(e.target.value)}
          />
        </div>
        <div>
          <label
            htmlFor={`${id}-actor`}
            className="mb-1 block text-sm font-medium"
          >
            {t.recommendations.form.actor} *
          </label>
          <input
            id={`${id}-actor`}
            className="field"
            maxLength={200}
            required
            value={actor}
            placeholder={t.recommendations.form.actorPlaceholder}
            aria-invalid={touched && actorMissing}
            aria-describedby={
              touched && actorMissing ? `${id}-actor-error` : undefined
            }
            onChange={(e) => setActor(e.target.value)}
          />
          {touched && actorMissing ? (
            <p
              id={`${id}-actor-error`}
              className="mt-1 text-sm font-medium text-high-fg"
            >
              {t.recommendations.form.actorRequired}
            </p>
          ) : null}
        </div>
      </div>
      {mutation.isError ? (
        <p role="alert" className="text-sm font-medium text-high-fg">
          {t.recommendations.form.failed}:{" "}
          {mutation.error.detail ?? mutation.error.message}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={mutation.isPending}
        >
          {mutation.isPending
            ? t.recommendations.form.submitting
            : t.recommendations.form.submit}
        </button>
        <button
          type="button"
          className="btn"
          onClick={onCancel}
          disabled={mutation.isPending}
        >
          {t.recommendations.form.cancel}
        </button>
      </div>
    </form>
  );
}

type DecisionRow = NonNullable<
  ReturnType<typeof useDecisions>["data"]
>["items"][number];

const decisionColumns: Column<DecisionRow>[] = [
  {
    key: "created_at",
    header: t.decisions.columns.createdAt,
    render: (d) => (
      <span className="tabular-nums">{fmtDateTime(d.created_at)}</span>
    ),
  },
  {
    key: "action",
    header: t.decisions.columns.action,
    render: (d) => <strong>{t.decisions.actionPast[d.action]}</strong>,
  },
  {
    key: "alternative",
    header: t.decisions.columns.alternative,
    render: (d) =>
      d.alternative_org_code ? (
        <span>
          {d.alternative_org_name ?? d.alternative_org_code}
          <span className="block text-sm text-muted">
            {d.alternative_org_code}
          </span>
        </span>
      ) : (
        t.decisions.general
      ),
  },
  { key: "actor", header: t.decisions.columns.actor, render: (d) => d.actor },
  {
    key: "comment",
    header: t.decisions.columns.comment,
    render: (d) => d.comment ?? t.common.noData,
  },
];

function DecisionHistory({ org, profile }: { org: string; profile: string }) {
  const query = useDecisions(org, profile);
  return (
    <div className="space-y-2" aria-live="polite">
      <h3 className="text-lg font-semibold">{t.decisions.title}</h3>
      <p className="text-sm text-muted">{t.decisions.caption}</p>
      {query.isPending ? (
        <TableSkeleton rows={2} columns={5} />
      ) : query.isError ? (
        <ErrorState
          error={query.error}
          onRetry={() => void query.refetch()}
          compact
        />
      ) : (
        <DataTable
          columns={decisionColumns}
          rows={query.data.items}
          rowKey={(d) => String(d.id)}
          caption={t.decisions.title}
          empty={t.decisions.empty}
          maxHeight="max-h-80"
        />
      )}
    </div>
  );
}
